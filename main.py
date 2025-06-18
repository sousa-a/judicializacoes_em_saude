# ### OBJETIVO: CONSULTAR AÇÕES DE JUDICIALIZAÇÕES EM SAÚDE E EXTRAIR INFORMAÇÕES DE SEQUESTRO E OUTROS
# ### ELEMENTOS CONTIDOS NAS DECISÕES, SENTENÇAS

# # Sequestro judicial: decisão judicial que determina a apreensão e custódia de bens (compulsória), a fim de garantir
# # a execução de uma sentença futura ou o ressarcimento de danos.

# # Sequestro de Verbas Públicas: decisão judicial que determina a apreensão e custódia de verbas públicas (compulsória),
# # caso o Estado não cumpra a obrigação.
# # Termos comuns:
# # "ordeno o sequestro|defiro o sequestro|determino o sequestro|autorizo o sequestro..."

# # Bloqueio: é a retenção de valores em contas públicas, impedindo seu uso até que haja decisão judicial sobre sua destinação.
# # Os valores ficam "congelados" na conta do ente público. Realizado pelo sistema BACENJUD (antigo SISBAJUD).
# # Pode ser convertido em sequestro.
# # Termos comuns: 
# # "ordeno o bloqueio|defiro o bloqueio|determino o bloqueio|autorizo o bloqueio"

# # Transferência: É o repasse dos valores já sequestrados ou bloqueados para o beneficiário final — geralmente o hospital,
# # distribuidor, clínica, farmácia, laboratório ou o próprio paciente.
# # Por vezes, finaliza a etapa de cumprimento de decisão judicial.
# # Pode envolver pagamento de fornecedores ou reembolso ao autor da ação, conforme o caso.
# # Termos comuns:
# # "ordeno a transferência|determino a transferência|autorizo a transferência|defiro a transferência..."

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

# Termos comuns presentes nos documentos consultados que autoriza/determinam bloqueio, sequestro ou transferência
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
options.add_argument("--headless") #ativa o modo headless
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
        link_processo = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.XPATH,
                 "/html/body/div[5]/div/div/div/div[2]/form/div[2]/div/table/tbody/tr/td[1]/a")
            )
        )
        link_processo.click()
        time.sleep(5)
    except TimeoutException:
        print("    → nenhum resultado retornado para este número. Passando para o próximo elemento da lista.")
        continue

    proc_handle = driver.window_handles[-1]
    driver.switch_to.window(proc_handle)

    arquivado = "SIM" if "Arquivado Definitivamente" in driver.page_source else "NÃO"

    try:
        total_pag = int(driver.find_element(
            By.XPATH,
            '/html/body/div[5]/div/div/div/div[2]/table/tbody/tr[2]/td/table/tbody/tr/td/div[6]/div[2]/div[2]/'
            'div/form/table/tbody/tr[1]/td[3]'
        ).text.strip())
    except NoSuchElementException:
        total_pag = 1

    # Percorre cada uma das páginas contendo e busca documentos do tipo decisão, sentença, alvará e despacho.
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

            # Extrai os valores para os campos dataHora e tipoDocumento
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

            # Às vezes, o site da consulta pública pode ficar sobrecarregado
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

            # Tenta localizar elemento .folha e faz fallback
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
    with open(arquivo_dia, "a", newline="") as f:
        df_inc.to_csv(f, sep="\t", index=False, header=not os.path.getsize(f.name))

    driver.close()
    driver.switch_to.window(driver.window_handles[0])

# Consolida todos os resultados e salva
pd.DataFrame(registros).to_csv(
    "resultados_sequestro_tjdft.csv", sep="\t", index=False, encoding="utf-8-sig"
)

elapsed = time.time() - start_time #Tempo transcorrido
h, r = divmod(int(elapsed), 3600)
m, s = divmod(r, 60)
print(f"\nConcluído – arquivos salvos. Tempo total: {h:02d}:{m:02d}:{s:02d}")