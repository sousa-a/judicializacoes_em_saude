from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    ElementClickInterceptedException,
    TimeoutException,
)
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import pandas as pd
import time, re, os
from datetime import date

# Essa função usa regex para se certificar que o número do processo siga o padrão CNJ
import re as _re
def formata_cnj(raw: str) -> str:
    """
    Converte “07139631420238070016” (ou qualquer formato sem pontuação)
    para “0713963-14.2023.8.07.0016”.
    Se já estiver no padrão CNJ, devolve sem alteração.
    """
    if _re.fullmatch(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}", raw):
        return raw
    digitos = _re.sub(r"\D", "", raw).zfill(20)
    return (
        f"{digitos[0:7]}-{digitos[7:9]}."
        f"{digitos[9:13]}."
        f"{digitos[13]}."
        f"{digitos[14:16]}."
        f"{digitos[16:20]}"
    )

# Termos comuns presentes nos documentos consultados que autorizam/determinam bloqueio, sequestro ou transferência
termos_bloqueio = (
    "ordeno o bloqueio|defiro o bloqueio|determino o bloqueio|"
    "defiro o pedido de tutela de urgência para determinar o bloqueio|"
    "para determinar o bloqueio|autorizo o bloqueio"
)
termos_sequestro = (
    "ordeno o sequestro|defiro o sequestro|determino o sequestro|autorizo o sequestro|"
    "ordeno o sequestro|proceda-se, com urgência, ao sequestro|proceda-se ao sequestro|"
    "justifica-se a medida excepcional de sequestro|se legitima o sequestro"
)
termos_transferencia = (
    "ordeno a transferência|determino a transferência|autorizo a transferência|"
    "autorizo a expedição de alvará judicial para o levantamento dos valores sequestrados|"
    "defiro a transferência|ordeno a expedição de alvará|determino a expedição de alvará|"
    "defiro a expedição de alvará|autorizo a expedição de alvará"
)
re_seq   = re.compile(termos_sequestro,     flags=re.I)
re_bloq  = re.compile(termos_bloqueio,      flags=re.I)
re_trans = re.compile(termos_transferencia, flags=re.I)

# Argumentos do Selenium
options = Options()
options.add_argument("--disable-notifications")
options.add_argument("--headless")  # ativa o modo headless
service = Service(ChromeDriverManager().install())
driver  = webdriver.Chrome(service=service, options=options)
wait    = WebDriverWait(driver, 10)

# Lê o arquivo contendo a lista de processos que serão consultados
df_proc = pd.read_csv("processos.csv", sep="\t", dtype={"processos": str})
df_proc["processos"] = df_proc["processos"].apply(formata_cnj)
processos      = df_proc["processos"].tolist()
total_proc     = len(processos)
print(f"Total de processos na lista: {total_proc}")

registros  = []
start_time = time.time()

def _xpath_valor_por_label(lbl: str) -> str:
    """
    Retorna o texto dentro do <div class="col-sm-12"> logo após o <label>
    cujo conteúdo contém *lbl* (case/acentos tolerantes).
    """
    try:
        el = driver.find_element(
            By.XPATH,
            f"//div[@class='propertyView ']"
            f"[div[@class='name']/label[contains(translate(.,"
            f"'ÁÀÂÃÉÈÊÍÌÎÓÒÔÕÚÙÛÇ','AAAEEEIIOOOUUC'),'{lbl.upper()}')]]"
            f"//div[@class='col-sm-12' and normalize-space()]"
        )
        return el.text.strip()
    except NoSuchElementException:
        return ""

cpf_re  = re.compile(r"\d{3}\.\d{3}\.\d{3}-\d{2}")
cnpj_re = re.compile(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}")

def _limpa_nome_parte(raw: str) -> str:
    """
    Remove CPF/CNPJ e descrições, deixando apenas o nome.
    Ex.: "ANTUANETE XAVIER - CPF:  (EXEQUENTE)" ➜ "ANTUANETE XAVIER"
    """
    txt = cpf_re.sub("", raw)
    txt = cnpj_re.sub("", txt)
    txt = re.sub(r"CPF:|CNPJ:", "", txt, flags=re.I)
    txt = re.sub(r"\(.*?\)", "", txt)        # remove descrições entre parênteses
    txt = txt.split(" - ")[0]               # considera o que vem antes do primeiro hífen
    txt = re.sub(r"\s{2,}", " ", txt)       # colapsa múltiplos espaços
    return txt.strip(" -").strip()

def _extrai_polo_ativo() -> tuple[str, str]:
    """
    Percorre a tabela 'PoloAtivoResumidoList' e devolve (nome, cpf) do
    primeiro participante 'parte', ignorando advogados/representantes.
    """
    linhas = driver.find_elements(
        By.XPATH,
        "//table[contains(@id,'PoloAtivoResumidoList')]//tbody/tr"
    )
    for ln in linhas:
        try:
            cel = ln.find_element(By.XPATH, "./td[1]")
        except NoSuchElementException:
            continue
        txt = cel.text.replace("\n", " ").strip()
        if any(p in txt.upper() for p in ["ADVOGADO", "REPRESENTANTE", "PROCURADORIA"]):
            continue
        mcpf = cpf_re.search(txt)
        cpf  = mcpf.group() if mcpf else ""
        nome = txt.replace(cpf, "").strip(" -")
        return _limpa_nome_parte(nome), cpf
    return "", ""


def _primeiro_participante(tabela_id_regex: str):
    try:
        cel = driver.find_element(
            By.XPATH,
            f"//table[contains(@id,'{tabela_id_regex}')]//tbody/tr[1]/td[1]"
        )
        txt = cel.text.replace('\n', ' ').strip()
        return txt
    except NoSuchElementException:
        return ""

# Itera sobre a lista de processos
for idx, processo in enumerate(processos, start=1):
    arquivo_dia = f"{date.today()}consulta_acoes_judiciais_sesdf_tjdft.csv"
    ja_no_csv   = os.path.exists(arquivo_dia) and any(
        processo in ln for ln in open(arquivo_dia, "r", encoding="utf-8")
    )

    if ja_no_csv:
        print(f"[{idx}/{total_proc}] {processo} – processo já consultado.")
        continue
    else:
        print(f"[{idx}/{total_proc}] {processo} – consultando…")

    # Site da consulta pública (PJE) do TJDFT
    driver.get("https://pje-consultapublica.tjdft.jus.br/consultapublica/ConsultaPublica/listView.seam")
    time.sleep(3)

    campo = driver.find_element(
        By.XPATH, '//*[@id="fPP:numProcesso-inputNumeroProcessoDecoration:numProcesso-inputNumeroProcesso"]'
    )
    campo.clear()
    campo.send_keys(processo)
    driver.find_element(By.XPATH, '//*[@id="fPP:searchProcessos"]').click()
    time.sleep(8)

    try:
        ultima_mov_elem = driver.find_element(
            By.XPATH,
            "//table[@id='fPP:processosTable']//td[contains(@id,':j_id267')]"
        )
        ultima_mov = ultima_mov_elem.text.strip()
    except NoSuchElementException:
        ultima_mov = ""

    try:
        link_processo = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.XPATH,
                 "/html/body/div[5]/div/div/div/div[2]/form/div[2]/div/table/tbody/tr/td[1]/a")
            )
        )
        link_processo.click()
        time.sleep(5)
    except TimeoutException:
        print("    → nenhum resultado retornado para este número.")
        continue

    # Abre detalhes do processo em nova janela
    proc_handle = driver.window_handles[-1]
    driver.switch_to.window(proc_handle)

    try:
        classe_judicial = driver.find_element(
            By.XPATH,
            '/html/body/div[5]/div/div/div/div[2]/table/tbody/tr[2]/td/table/tbody/tr/td/'
            'form/div/div[1]/div[3]/table/tbody/tr[1]/td[3]/span/div/div[2]'
        ).text.strip()
    except NoSuchElementException:
        classe_judicial = ""

    try:
        data_distribuicao = driver.find_element(
            By.XPATH,
            '/html/body/div[5]/div/div/div/div[2]/table/tbody/tr[2]/td/table/tbody/tr/td/'
            'form/div/div[1]/div[3]/table/tbody/tr[1]/td[2]/span/div/div[2]'
        ).text.strip()
    except NoSuchElementException:
        # fallback para método baseado em label
        data_distribuicao = _xpath_valor_por_label("DATA DA DISTRIBUICAO")

    try:
        orgao_elem = driver.find_element(
            By.XPATH,
            '/html/body/div[5]/div/div/div/div[2]/table/tbody/tr[2]/td/table/tbody/tr/td/'
            'form/div/div[1]/div[3]/table/tbody/tr[2]/td[3]/span/div/div[2]/div'
        )
        linhas_org = orgao_elem.text.strip().splitlines()
        orgao_julgador = linhas_org[1].strip() if len(linhas_org) > 1 else orgao_elem.text.strip()
    except NoSuchElementException:
        orgao_julgador = ""


    # Chama a função extrai_polo_ativo() para obter o nome e o cpf
    polo_ativo, cpf_polo_ativo = _extrai_polo_ativo()

    try:
        polo_passivo_raw = driver.find_element(
            By.XPATH,
            "/html/body/div[5]/div/div/div/div[2]/table/tbody/tr[2]/td/table/tbody/tr/"
            "td/div[2]/div/div[2]/span/div/table/tbody/tr/td[1]/span/div/span"
        ).text.replace('\n', ' ').strip()
    except NoSuchElementException:
        polo_passivo_raw = ""

    mcnpj  = cnpj_re.search(polo_passivo_raw)
    cnpj_polo_passivo = mcnpj.group() if mcnpj else ""
    polo_passivo      = _limpa_nome_parte(polo_passivo_raw.replace(cnpj_polo_passivo, ""))

    # Extrai a informação acerca do arquivamento do processo
    arquivado = "SIM" if "Arquivado Definitivamente" in driver.page_source else "NÃO"

    try:
        total_pag = int(driver.find_element(
            By.XPATH,
            '/html/body/div[5]/div/div/div/div[2]/table/tbody/tr[2]/td/table/tbody/tr/td/'
            'div[6]/div[2]/div[2]/div/form/table/tbody/tr[1]/td[3]'
        ).text.strip())
    except NoSuchElementException:
        total_pag = 1

    # Percorre as páginas de documentos
    for pag in range(1, total_pag + 1):
        if pag > 1:
            driver.execute_script(
                'var el=document.getElementById("j_id151:j_id662:j_id663Input");'
                f'el.value="{pag}";el.dispatchEvent(new Event("change"));'
            )
            time.sleep(2)

        print(f"    • página {pag}/{total_pag}")
        wait.until(EC.presence_of_all_elements_located(
            (By.XPATH, "//tbody[@id='j_id151:processoDocumentoGridTab:tb']/tr")
        ))
        linhas = driver.find_elements(
            By.XPATH, "//tbody[@id='j_id151:processoDocumentoGridTab:tb']/tr"
        )

        for linha in linhas:
            try:
                anchor = linha.find_element(By.XPATH, ".//td[1]//a")
                texto_anchor = anchor.text.strip()
            except:
                continue

            data_hora = tipo_raw = ""
            for ln in texto_anchor.splitlines():
                ln = ln.strip()
                if re.match(r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}", ln):
                    partes = ln.split(" - ", 1)
                    data_hora = partes[0].strip()
                    tipo_raw  = partes[1].strip() if len(partes) > 1 else ""
                    break

            if not any(k in texto_anchor.lower() for k in ["decisão", "decisao", "sentença", "sentenca", "alvará", "alvara", "despacho"]):
                continue

            anchor_id = anchor.get_attribute("id")
            for tent in range(4):
                try:
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", anchor)
                    anchor.click()
                    break
                except (StaleElementReferenceException, ElementClickInterceptedException):
                    time.sleep(0.5)
                    anchor = driver.find_element(By.ID, anchor_id)
                    if tent == 3:
                        driver.execute_script("arguments[0].click();", anchor)

            wait.until(lambda d: len(d.window_handles) > 1)
            child = [h for h in driver.window_handles if h != proc_handle][-1]
            driver.switch_to.window(child)

            try:
                texto_elem = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CLASS_NAME, "folha"))
                )
                texto_doc = texto_elem.text
            except TimeoutException:
                texto_doc = driver.find_element(By.TAG_NAME, "body").text

            if not texto_doc.strip():
                driver.close()
                driver.switch_to.window(proc_handle)
                continue

            id_doc = texto_doc.split("ID do documento:")[1].split()[0] if "ID do documento:" in texto_doc else ""
            m_ass  = re.search(r"Assinado eletronicamente por:\s*(.+)", texto_doc)
            assinante = m_ass.group(1).split("\n")[0].strip() if m_ass else ""

            contem_seq  = "SIM" if re_seq.search(texto_doc)   else "NÃO"
            contem_bloq = "SIM" if re_bloq.search(texto_doc)  else "NÃO"
            contem_tran = "SIM" if re_trans.search(texto_doc) else "NÃO"

            trecho = ""
            if contem_seq == "SIM":
                for p in texto_doc.split("\n\n"):
                    if re_seq.search(p):
                        trecho = p.strip(); break

            m_val = re.search(r"R\$[\s]*\d{1,3}(?:\.\d{3})*,\d{2}", texto_doc)
            valor_capturado = m_val.group() if m_val else ""
            valor_total = valor_capturado if any(x == "SIM" for x in [contem_seq, contem_bloq, contem_tran]) else ""

            registros.append({
                "poloAtivo": polo_ativo,
                "cpfPoloAtivo": cpf_polo_ativo,
                "poloPassivo": polo_passivo,
                "cnpjPoloPassivo": cnpj_polo_passivo,
                "orgaoJulgador": orgao_julgador,
                "classeJudicial": classe_judicial,
                "dataDistribuicao": data_distribuicao,
                "ultimaMovimentacao": ultima_mov,
                "numeroProcesso": processo,
                "idDocumento": id_doc,
                "tipoDocumento": tipo_raw,
                "dataHora": data_hora,
                "assinadoPor": assinante,
                "contemAutorizacaoSequestro":     contem_seq,
                "contemAutorizacaoBloqueio":      contem_bloq,
                "contemAutorizacaoTransferencia": contem_tran,
                "valorTotal": valor_total,
                "arquivado": arquivado,
                "textoDocumento": trecho
            })

            driver.close()
            driver.switch_to.window(proc_handle)

    # Grava o incremento no CSV diário
    df_inc = pd.DataFrame(registros)

    col_order = [
        "poloAtivo", "cpfPoloAtivo", "poloPassivo", "cnpjPoloPassivo",
        "orgaoJulgador", "classeJudicial", "dataDistribuicao",
        "ultimaMovimentacao", "numeroProcesso", "idDocumento",
        "tipoDocumento", "dataHora", "assinadoPor",
        "contemAutorizacaoSequestro", "contemAutorizacaoBloqueio",
        "contemAutorizacaoTransferencia", "valorTotal",
        "arquivado", "textoDocumento"
    ]
    df_inc = df_inc[col_order]

    with open(arquivo_dia, "a", newline="") as f:
        df_inc.to_csv(f, sep="\t", index=False, header=not os.path.getsize(f.name))

    driver.close()
    driver.switch_to.window(driver.window_handles[0])

elapsed = time.time() - start_time  # Tempo transcorrido
# Converte de segundos para o formato hh:mm:ss
h, r = divmod(int(elapsed), 3600)
m, s = divmod(r, 60)
print(f"\nConcluído – arquivos salvos. Tempo total: {h:02d}:{m:02d}:{s:02d}")
