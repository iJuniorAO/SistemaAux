import streamlit as st
import requests
import re
import io
import json
import pandas as pd
from datetime import datetime, timezone, timedelta


# -----------------------------------------------------------------------------
# Auxiliar
# -----------------------------------------------------------------------------
def _tratar_url_onedrive(input_texto: str) -> str:
    url_match = re.search(r'src="([^"]+)"', input_texto)
    url = url_match.group(1) if url_match else input_texto

    # 2. Ajuste para SharePoint Business
    # Se for link de embed do SharePoint, mudamos para o modo de download
    if "sharepoint.com" in url:

        if "embed.aspx" in url:
            # Transforma o link de embed em um link de ação de download
            url = url.replace("embed.aspx", "download.aspx")
        elif "download=1" not in url:
            # Se for link de compartilhamento normal, força o download
            url = url + ("&" if "?" in url else "?") + "download=1"
    else:
        # Caso seja OneDrive Pessoal
        url = url.replace("embed", "download")
    return url


@st.cache_data(ttl=600, show_spinner=False)
def obter_ultima_modificacao(url: str) -> str:
    try:
        resp = requests.head(url, allow_redirects=True, timeout=20)
        # Tenta obter Last-Modified ou ETag como fallback de validação
        return resp.headers.get("Last-Modified") or resp.headers.get("ETag") or ""
    except Exception:
        return ""


# -----------------------------------------------------------------------------
# Dados Completos
# -----------------------------------------------------------------------------


@st.cache_data(show_spinner="Baixando dados do OneDrive...", show_time=True)
def _obter_dados_cached(url: str, last_modified: str):
    response = requests.get(url, timeout=20)
    response.raise_for_status()

    # Ajuste automático ou forçado de encoding para TXT/CSV
    response.encoding = response.apparent_encoding or "utf-8"

    return response.text


# -----------------------------------------------------------------------------
# Funções Principais
# -----------------------------------------------------------------------------
def carregar_dados_onedrive(input_texto):
    try:
        url = _tratar_url_onedrive(input_texto)
        data_modificacao = obter_ultima_modificacao(url)

        # Ao passar data_modificacao para o cache, se ela mudar, o Streamlit re-executa a requisição get
        texto = _obter_dados_cached(url, data_modificacao)

        return {"falha": False, "resp": texto, "data": data_modificacao}
    except Exception as e:
        st.error(f"Erro ao processar URL: {e}")
        return {"falha": True, "resp": None, "data": None}


@st.cache_data(
    ttl=7200, show_spinner="Carregando dados txt", show_time=True, scope="session"
)
def carregar_dados_onedrive_rp(input_texto):
    try:
        # 1. Limpeza: Se o usuário colou o <iframe>, extrai apenas a URL
        url_match = re.search(r'src="([^"]+)"', input_texto)
        url = url_match.group(1) if url_match else input_texto

        # 2. Ajuste para SharePoint Business
        if "sharepoint.com" in url:
            if "embed.aspx" in url:
                url = url.replace("embed.aspx", "download.aspx")
            elif "download=1" not in url:
                url = url + ("&" if "?" in url else "?") + "download=1"
        else:
            # Caso seja OneDrive Pessoal
            url = url.replace("embed", "download")

        # 3. Faz a requisição
        response = requests.get(url, timeout=20)
        response.raise_for_status()

        # Garante a codificação correta para caracteres especiais/acentos
        response.encoding = response.apparent_encoding or "utf-8"

        # 4. Obtém a data de modificação no header da resposta
        data_modificacao = response.headers.get("Last-Modified")

        # 5. Processa o conteúdo em formato CSV
        # O io.StringIO transforma o texto da resposta em um buffer de arquivo para o pandas
        # Dica: altere sep=";" se o seu CSV usar ponto e vírgula como separador
        df = pd.read_csv(io.StringIO(response.text), sep=None, engine="python")

        return {
            "falha": False,
            "df": df,
            "resp_raw": response.text,
            "data": data_modificacao,
        }

    except Exception as e:
        st.error(f"Erro ao processar URL: {e}")
        return {"falha": True, "df": None, "resp_raw": None, "data": None}


def converte_ultima_modificacao(data_string):

    formato = "%a, %d %b %Y %H:%M:%S %Z"
    fuso_horario = timezone(timedelta(hours=-3))

    data_obj = datetime.strptime(data_string, formato).replace(tzinfo=timezone.utc)
    data_obj = data_obj.astimezone(fuso_horario)

    return data_obj


def abrir_arquivo_txt(arquivo, colunas=None):
    try:
        if isinstance(arquivo, str):
            arquivo = io.StringIO(arquivo)
        return pd.read_csv(
            arquivo, sep="|", header=None, names=colunas, encoding="latin1"
        )
    except Exception as e:
        st.error(f"Erro ao ler arquivo {e}")
        st.stop()


def ler_planilha(caminho_arquivo, colunas=None):
    """Lê o Excel e define os nomes das colunas conforme o notebook"""

    try:
        df = pd.read_excel(caminho_arquivo, header=None, names=colunas)
        return {"erro": False, "df": df}
    except TypeError as e:
        print(f"ERRO - Tentando usar openpyxl...")
        try:
            df = pd.read_excel(
                caminho_arquivo, header=None, names=colunas, engine="calamine"
            )
            return {"erro": False, "df": df}
        except TypeError as e:
            print(f"ERRO - Não foi possível abrir {e}")
            return {"erro": True, "df": df}
        except ValueError as e:
            print(f"ERRO - Tipo de arquivo errado")
            return {"erro": True, "df": df}


def pandas_ler_excel(caminho_arquivo, colunas=None):
    """Lê o Excel e define os nomes das colunas conforme o notebook"""

    try:
        df = pd.read_excel(caminho_arquivo, header=None, names=colunas)
        return {"erro": False, "df": df}
    except TypeError as e:
        print(f"ERRO - Tentando usar openpyxl...")
        try:
            df = pd.read_excel(
                caminho_arquivo, header=None, names=colunas, engine="calamine"
            )
            return {"erro": False, "df": df}
        except TypeError as e:
            print(f"ERRO - Não foi possível abrir {e}")
            return {"erro": True, "df": df}


# -----------------------------------------------------------------------------
# Guia Cega
# -----------------------------------------------------------------------------


def layout_guia_cega(resposta_xml):

    css_contraste_tabela = """
    <style>
        /* Estilização de alto contraste para st.table (tabelas estáticas) */
        [data-testid="stTable"] th {
            background-color: #F2F2F2 !important;
            color: #000000 !important;
            font-weight: 800 !important;
            border-bottom: 2px solid #000000 !important;
        }
        [data-testid="stTable"] td {
            color: #111111 !important;
            font-weight: 500 !important;
            border: 1px dotted #d3d3d3 !important;
        }
    }
    </style>
    """

    st.markdown(css_contraste_tabela, unsafe_allow_html=True)

    df_log = resposta_xml["df"][["Codigo Fornecedor", "Descrição"]].copy()
    df_log = df_log.rename(columns={"Codigo Fornecedor": "Cod Forn."})
    df_log.index = resposta_xml["df"]["Item"]

    df_log["Un por Cx"] = ""
    df_log["Qtd Cx Contada"] = ""
    df_log["Data Validade"] = ""
    df_log["Cx por Palete"] = ""

    coluna1, coluna2 = st.columns(2, vertical_alignment="bottom")
    with coluna1:
        st.markdown("## :material/Package: Logística: Conferência Cega")
    with coluna2:
        st.write("Conferido por: _________________")

    st.markdown(
        f"#### Emitente: :blue[{resposta_xml["emitente"]["emitente_fantasia"]}] - {resposta_xml["emitente"]["emitente_nome"]}"
    )
    st.markdown(f"Nº NFe: :blue[{resposta_xml["nr_Nfe"]}]")

    colun1, colun2, colun3, colun4 = st.columns(4, vertical_alignment="center")
    with colun1:
        st.write(r"______ / ______")
        st.markdown(":_____________ Ordem")
    with colun2:
        st.checkbox("Descarga Normal")
        st.checkbox("Descarga Isenta")
    with colun3:
        st.checkbox("Descarga Fixa")
        st.markdown("R$:_________________")
    with colun4:
        st.checkbox("Lista")
        st.checkbox("Divisão")

    return df_log


# -----------------------------------------------------------------------------
# Acessos
# -----------------------------------------------------------------------------


def validar_acesso(roles_permitidas=["administrador"]):
    # 1. Verifica se está logado
    if st.session_state.get("perfil") == "none" or "perfil" not in st.session_state:
        st.markdown("# :red[:material/lock:] ACESSO NEGADO")
        st.text("É necessário realizar o login para continuar.")
        if st.button("Ir para Login"):
            st.switch_page("login.py")
        st.stop()

    perfil = st.session_state.perfil

    if perfil.get("status") == "pendente":
        st.warning("# :material/warning: USUÁRIO COM PENDÊNCIA")
        st.text("Entrar em contato com a equipe técnica.")
        st.stop()

    # 3. Verifica permissão de nível
    if perfil.get("role") not in roles_permitidas:
        st.markdown("# :red[:material/block: ACESSO NEGADO]")
        st.text("Seu usuário não possui permissão para esta página.")
        st.stop()


def set_cookies(cookies: dict, days=7):
    """
    Grava múltiplos cookies em uma única execução JavaScript
    e recarrega a aplicação somente após finalizar.
    """

    dados = {}

    for name, value in cookies.items():
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)

        dados[str(name)] = str(value)

    cookies_js = json.dumps(dados, ensure_ascii=False)
    days_js = json.dumps(float(days))

    js_code = f"""
    <script>
    (() => {{
        const cookies = {cookies_js};
        const days = {days_js};

        const maxAge = Math.floor(days * 86400);

        const secure = location.protocol === "https:"
            ? "; Secure"
            : "";

        Object.entries(cookies).forEach(([name, value]) => {{
            document.cookie =
                encodeURIComponent(name) + "=" +
                encodeURIComponent(value) +
                "; Max-Age=" + maxAge +
                "; Path=/; SameSite=Lax" + secure;
        }});

        console.log("Cookies gravados:", Object.keys(cookies));
        window.setTimeout(() => window.location.reload(), 100);

    }})();
    </script>
    """

    st.html(js_code, unsafe_allow_javascript=True)


def set_cookie(name, value, days=7):
    """Grava um único cookie sem provocar reload."""

    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)

    name_js = json.dumps(str(name))
    value_js = json.dumps(str(value))
    days_js = json.dumps(float(days))

    js_code = f"""
    <script>
    (() => {{
        const secure = location.protocol === "https:"
            ? "; Secure"
            : "";

        document.cookie =
            encodeURIComponent({name_js}) + "=" +
            encodeURIComponent({value_js}) +
            "; Max-Age=" + Math.floor({days_js} * 86400) +
            "; Path=/; SameSite=Lax" + secure;
    }})();
    </script>
    """

    st.html(js_code, unsafe_allow_javascript=True)


def buscar_perfil_bd(supabase, user_id):
    try:
        response = supabase.table("perfis").select("*").eq("user_id", user_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        st.error("Erro: Não foi possivel realizar login")
        print(e)
        st.stop()


def delete_cookie(name):
    name_js = json.dumps(str(name))

    js_code = f"""
    <script>
    (() => {{
        document.cookie =
            {name_js} + "=; Max-Age=0; Path=/; SameSite=Lax";
    }})();
    </script>
    """

    st.html(js_code, unsafe_allow_javascript=True)


def delete_cookies(names):
    names_js = json.dumps([str(name) for name in names])

    js_code = f"""
    <script>
    (() => {{
        {{}};
        const names = {names_js};

        names.forEach(name => {{
            document.cookie =
                encodeURIComponent(name) +
                "=; Max-Age=0; Path=/; SameSite=Lax";
        }});

        window.setTimeout(() => window.location.reload(), 100);

    }})();
    </script>
    """

    st.html(js_code, unsafe_allow_javascript=True)


def log_off():
    st.session_state.pop("user", None)
    st.session_state.pop("session", None)
    st.session_state.pop("perfil", None)
    delete_cookies(["sb_access_token", "sb_refresh_token", "perfil"])
    st.session_state.perfil = {"role": "client"}


def restore_session(supabase):
    """Restaura a sessão usando os tokens persistidos nos cookies."""
    if st.session_state.get("user") is None:
        access_token = st.context.cookies.get("sb_access_token")
        refresh_token = st.context.cookies.get("sb_refresh_token")

        if access_token and refresh_token:
            try:
                res = supabase.auth.set_session(access_token, refresh_token)
                if res.user:
                    perfil = buscar_perfil_bd(supabase, res.user.id)
                    if perfil is None:
                        raise ValueError("Perfil do usuário não encontrado.")

                    st.session_state["user"] = res.user
                    st.session_state["session"] = res.session
                    st.session_state["perfil"] = perfil

            except Exception as e:
                st.error(f"Não foi possível restaurar a sessão: {e}")
                log_off()
