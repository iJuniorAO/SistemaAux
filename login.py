import streamlit as st
from bancoDados import inicia_conexao_bancoDados, tratar_erros_supabase
from utils import buscar_perfil_bd, delete_cookies, restore_session, set_cookies


def realizar_login(email, senha):
    try:
        resposta = supabase.auth.sign_in_with_password(
            {"email": email, "password": senha}
        )
        return resposta
    except Exception as e:
        tratar_erros_supabase(e)


def cadastrar_usuario(nome, email, senha, departamento):
    try:
        # 1. Cria o usuário no Auth (Sistema de Login)
        auth_res = supabase.auth.sign_up({"email": email, "password": senha})

        if auth_res.user:
            user_uuid = auth_res.user.id

            # 2. Cria a linha na sua tabela 'perfis' manualmente
            perfil_data = {
                "id": user_uuid,
                "nome": nome,
                "dept": departamento,
                "status": "ativo",
                "permissoes": "leitura",
            }

            supabase.table("perfis").insert(perfil_data).execute()
            st.success(
                "Cadastro realizado! Verifique seu e-mail (se a confirmação estiver ativa)."
            )
        else:
            st.error("Erro ao gerar usuário. Verifique se o e-mail já existe.")

    except Exception as e:
        st.error(f"Erro no processo de cadastro: {e}")


def valida_senha(senha, senha_repetida):
    if senha == "":
        st.error("A senha não pode estar vazia")
        return False
    if len(senha) <= 8:
        st.error("A senha precisa ter no mínimo 8 caracteres")
        return False
    if senha != senha_repetida:
        st.error("As senhas precisam ser iguais")
        return False

    return True


def supabase_update_senha(senha):
    try:
        response = supabase.auth.update_user({"password": senha})

        st.success("Senha atualizada com sucesso")
        return True
    except Exception as e:
        tratar_erros_supabase(e)


def primeiro_acesso():
    st.markdown("# :red[:material/Editor_Choice: Primeiro Acesso]")

    if perfil["nome"] == None:
        with st.container(border=True):
            st.markdown("### Alterar Nome")
            col1, col2 = st.columns([0.8, 0.2], vertical_alignment="bottom")
            username = col1.text_input("Digite seu nome: ", key="renameSenha")

            if col2.button("Salvar", key="confirmaNome", width="stretch"):
                try:
                    resposta = (
                        supabase.table("perfis")
                        .update({"nome": username})
                        .eq("user_id", perfil["user_id"])
                        .execute()
                    )
                    if resposta.data:
                        st.rerun()  # atualizado
                    else:
                        st.error("Erro ao atualizar")
                except Exception as e:
                    st.error(e)
        st.stop()

    with st.form("alteraSenha"):
        st.markdown("### Alterar senha")

        senha = st.text_input("Nova Senha", type="password", key="senha")
        senha_Repetido = st.text_input(
            "Repetir Senha", type="password", key="senhaRepetido"
        )
        if st.form_submit_button("Confirmar", key="confirmaSenha"):
            if valida_senha(senha, senha_Repetido):
                if supabase_update_senha(senha):
                    try:
                        resposta = (
                            supabase.table("perfis")
                            .update({"status": "ativo"})
                            .eq("user_id", perfil["user_id"])
                            .execute()
                        )
                        if resposta.data:
                            st.rerun()  # atualizado
                        else:
                            st.error("Erro ao atualizar status")
                    except Exception as e:
                        st.error(e)
        st.stop()


st.set_page_config(page_title="Sistema de Acesso", layout="wide")

supabase = inicia_conexao_bancoDados()
restore_session(supabase)

if "user" not in st.session_state:
    st.session_state.user = None
    st.session_state.session = None

if st.session_state.user is None:  # SEM LOGIN
    tab_login, tab_cadastro, tab_reenvio = st.tabs(
        ["Acessar Conta", "Novo Registro", "Reenvio Confirmação"]
    )

    with tab_login:
        with st.form("form_login"):
            email_log = st.text_input("E-mail")
            senha_log = st.text_input("Senha", type="password")

            if st.form_submit_button("Entrar"):
                usuario = realizar_login(email_log, senha_log)
                if usuario:
                    perfil = buscar_perfil_bd(supabase, usuario.user.id)
                    if perfil is None:
                        supabase.auth.sign_out()
                        st.error("Não foi possível encontrar o perfil deste usuário.")
                    else:
                        st.session_state.user = usuario.user
                        st.session_state.session = usuario.session
                        st.session_state.perfil = perfil

                        set_cookies(
                            {
                                "sb_access_token": usuario.session.access_token,
                                "sb_refresh_token": usuario.session.refresh_token,
                            },
                            days=7,
                        )
    with tab_cadastro:
        st.write("Em desenvolvimento...")
    if False:  # CADASTRO
        with st.form("form_cadastro"):
            novo_nome = st.text_input("Nome Completo")
            novo_dept = st.selectbox(
                "Seu Departamento",
                ["Administrativo", "Financeiro", "RH", "TI", "Logística"],
            )
            novo_email = st.text_input("E-mail de Cadastro")
            nova_senha = st.text_input(
                "Defina uma Senha", type="password", help="Mínimo 6 caracteres"
            )

            if st.form_submit_button("Criar Conta"):
                if novo_nome and novo_email and len(nova_senha) >= 6:
                    cadastrar_usuario(novo_nome, novo_email, nova_senha, novo_dept)
                else:
                    st.warning("Preencha todos os campos corretamente.")
    with tab_reenvio:
        with st.form("ReenvioAutenticacao"):
            email_resend = st.text_input("E-mail", key="reenvioEmail")
            if st.form_submit_button("Reenviar"):
                response = supabase.auth.resend(
                    {
                        "type": "signup",
                        "email": email_resend,
                    }
                )
                st.success("E-mail Enviado")

else:  # LOGADO
    perfil = st.session_state.perfil

    with st.sidebar:
        if st.button("Sair do Sistema"):
            supabase.auth.sign_out()
            st.session_state.user = None
            st.session_state.perfil = {"role": "client"}
            delete_cookies(["sb_access_token", "sb_refresh_token", "perfil"])

        st.markdown(f"### :blue[{perfil['nome']}] !")
        st.markdown(f"{perfil['role'].title()}")

    if st.button("Sair do Sistema"):
        supabase.auth.sign_out()
        st.session_state.user = None
        st.session_state.perfil = {"role": "client"}
        delete_cookies(["sb_access_token", "sb_refresh_token", "perfil"])

    if perfil["status"] == "pendente":
        primeiro_acesso()
    else:
        st.markdown("# Home")
        st.markdown(f"### Bem vindo :blue[{perfil['nome']}] !")

    c1, c2, c3 = st.columns(3, vertical_alignment="bottom")
    c1.metric("Departamento", f":blue[{perfil['dept'].title()}]")
    c2.metric("Permisões", f" :blue[{perfil['role'].title()}]")

    st.divider()
    if perfil:
        if perfil["status"] != "ativo":
            c3.metric("Status", f":red[{perfil['status'].title()}]")
            st.markdown(
                "Devido ao status :red[pendente] alguns acessos poderão ser limitados"
            )
