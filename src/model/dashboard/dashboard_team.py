import os
import airbyte as ab
import pandas as pd
import matplotlib.pyplot as plt
import base64
from io import BytesIO
from dotenv import load_dotenv
import json

class TeamStats:
    def __init__(self,save_func,report_dir):
        self.save_func = save_func
        self.report_dir = report_dir
        load_dotenv()
        self.token = os.getenv("GITHUB_TOKEN")
        self.repository = os.getenv("GITHUB_REPOSITORY")  # Ex: 'leds-conectafapes/planner'
        if not self.token or not self.repository:
            raise ValueError("Configure GITHUB_TOKEN e GITHUB_REPOSITORY no .env")
        self.cache = ab.get_default_cache()
        self.members_df = pd.DataFrame()
        self.issues_df = pd.DataFrame()
        
    def fetch_data(self):
        print("🔄 Conectando ao GitHub e carregando dados...")
        source = ab.get_source(
            "source-github",
            install_if_missing=True,
            config={
                "repositories": [self.repository],
                "credentials": {"personal_access_token": self.token},
            }
        )
        source.check()
        
        # Buscar membros da equipe
        print("👥 Buscando membros das equipes...")
        source.select_streams(["team_members"])
        source.read(cache=self.cache)
        if "team_members" in self.cache:
            self.members_df = self.cache["team_members"].to_pandas()
            print(f"✅ {len(self.members_df)} membros de equipe carregados.")
            
            # Verificar estrutura do DataFrame para debug
            print(f"Colunas dos membros: {self.members_df.columns.tolist()}")
            if "login" not in self.members_df.columns and "user" in self.members_df.columns:
                print("Extraindo login do campo user para membros")
                sample = self.members_df["user"].iloc[0] if not self.members_df.empty else None
                print(f"Exemplo de user: {type(sample)} - {sample}")
        else:
            print("⚠️ Nenhum membro de equipe encontrado.")
            self.members_df = pd.DataFrame()
            
        # Buscar issues
        print("🎫 Buscando issues...")
        source.select_streams(["issues"])
        source.read(cache=self.cache)
        if "issues" in self.cache:
            self.issues_df = self.cache["issues"].to_pandas()
            print(f"✅ {len(self.issues_df)} issues carregadas.")
            print(self.cache)
            # Verificar estrutura do DataFrame para debug
            print(f"Colunas das issues: {self.issues_df.columns.tolist()}")
            if "assignee" in self.issues_df.columns:
                sample = self.issues_df["assignee"].iloc[0] if not self.issues_df.empty else None
                print(f"Exemplo de assignee: {type(sample)} - {sample}")
            if "assignees" in self.issues_df.columns:
                sample = self.issues_df["assignees"].iloc[0] if not self.issues_df.empty else None
                print(f"Exemplo de assignees: {type(sample)} - {sample}")
        else:
            print("⚠️ Nenhuma issue encontrada.")
            self.issues_df = pd.DataFrame()
    
    def extract_login(self, user_json):
        """Extrai o login de um objeto JSON de usuário"""
        try:
            user = json.loads(user_json) if isinstance(user_json, str) else user_json
            return user.get("login", "N/A")
        except Exception as e:
            print(f"Erro ao extrair login: {e}")
            return "N/A"
    
    def extract_assignees(self, assignees_json):
        """Extrai os logins dos assignees de um objeto JSON"""
        try:
            assignees = []
            if assignees_json is None or pd.isna(assignees_json):
                return assignees
                
            # Verificar se é uma lista ou objeto único
            if isinstance(assignees_json, list):
                assignees_list = assignees_json
            elif isinstance(assignees_json, dict):
                # É um único objeto de usuário
                if "login" in assignees_json:
                    return [assignees_json["login"]]
                return assignees
            elif isinstance(assignees_json, str):
                # Tentar converter string para objeto JSON
                try:
                    parsed = json.loads(assignees_json)
                    if isinstance(parsed, list):
                        assignees_list = parsed
                    elif isinstance(parsed, dict) and "login" in parsed:
                        return [parsed["login"]]
                    else:
                        return assignees
                except:
                    print(f"Não foi possível converter string para JSON: {assignees_json[:100]}")
                    return assignees
            else:
                print(f"Tipo de assignee inesperado: {type(assignees_json)}")
                return assignees
                
            # Processar a lista de assignees
            for assignee in assignees_list:
                if isinstance(assignee, dict) and "login" in assignee:
                    login = assignee.get("login", "")
                    if login:
                        assignees.append(login)
                elif isinstance(assignee, str):
                    assignees.append(assignee)
                    
            return assignees
            
        except Exception as e:
            print(f"Erro ao extrair assignees: {e}")
            print(f"Valor recebido: {type(assignees_json)} - {str(assignees_json)[:100]}")
            return []
    
    def process_data(self):
        """Processa os dados para análise"""
        if self.members_df.empty or self.issues_df.empty:
            print("⚠️ Dados insuficientes para processamento.")
            print("Membros: ", len(self.members_df), "Issues:", len(self.issues_df))
            return False
            
        # Processar membros da equipe
        if "login" not in self.members_df.columns and "user" in self.members_df.columns:
            self.members_df["login"] = self.members_df["user"].apply(self.extract_login)
        
        # Processar issues
        print("Processando issues...")
        self.issues_df["creator"] = self.issues_df["user"].apply(self.extract_login)
        
        # Inicializar a coluna assignees_list como lista vazia para cada issue
        self.issues_df["assignees_list"] = [[] for _ in range(len(self.issues_df))]
        
        # Processar o campo assignees (lista de múltiplos assignees)
        if "assignees" in self.issues_df.columns:
            print(f"Processando campo 'assignees'...")
            for idx, row in self.issues_df.iterrows():
                if pd.notna(row["assignees"]):
                    assignees = self.extract_assignees(row["assignees"])
                    if assignees:
                        self.issues_df.at[idx, "assignees_list"] = assignees
                        
        # Processar o campo assignee (único assignee)
        if "assignee" in self.issues_df.columns:
            print(f"Processando campo 'assignee'...")
            for idx, row in self.issues_df.iterrows():
                if pd.notna(row["assignee"]):
                    assignee = self.extract_assignees(row["assignee"])
                    if assignee:
                        # Evitar duplicatas se o assignee já estiver na lista
                        current_assignees = self.issues_df.at[idx, "assignees_list"]
                        for a in assignee:
                            if a not in current_assignees:
                                current_assignees.append(a)
                        self.issues_df.at[idx, "assignees_list"] = current_assignees
        
        # Imprimir informações sobre os assignees para debug
        assignee_counts = self.issues_df["assignees_list"].apply(len).value_counts()
        print(f"Distribuição de assignees por issue: {assignee_counts.to_dict()}")
        
        # Verificar se há alguma issue com assignees
        if self.issues_df["assignees_list"].apply(len).sum() > 0:
            print("Criando DataFrame explodido para assignees...")
            
            # Criar lista de dicionários para construir o DataFrame explodido manualmente
            # Esta abordagem evita problemas com índices duplicados
            exploded_data = []
            
            for idx, row in self.issues_df.iterrows():
                assignees = row["assignees_list"]
                if not assignees:  # Se não há assignees, pular
                    continue
                    
                for assignee in assignees:
                    # Criar um novo dicionário com os dados desta linha e o assignee específico
                    row_data = {col: row[col] for col in self.issues_df.columns if col != "assignees_list"}
                    row_data["assignee"] = assignee
                    exploded_data.append(row_data)
            
            # Criar DataFrame a partir da lista de dicionários
            if exploded_data:
                self.issues_exploded_df = pd.DataFrame(exploded_data)
                print(f"Criadas {len(self.issues_exploded_df)} linhas de assignee-issue")
            else:
                print("Nenhum dado para o DataFrame explodido")
                self.issues_exploded_df = pd.DataFrame()
                self.issues_exploded_df["assignee"] = []
        else:
            print("⚠️ Nenhum assignee encontrado nas issues.")
            self.issues_exploded_df = pd.DataFrame()
            self.issues_exploded_df["assignee"] = []
        
        return True
    
    def count_issues_by_member(self):
        """Conta as issues criadas e recebidas por cada membro"""
        # Preparar dados
        all_members = set()
        if "login" in self.members_df.columns:
            all_members = set(self.members_df["login"].dropna().unique())
        
        # Contar issues criadas por cada membro
        created_counts = pd.Series(dtype=int)
        if "creator" in self.issues_df.columns:
            created_counts = self.issues_df.groupby("creator").size()
        
        # Contar issues recebidas (assignee) por cada membro
        assigned_counts = pd.Series(dtype=int)
        if not self.issues_exploded_df.empty and "assignee" in self.issues_exploded_df.columns:
            # Garantir que assignee não seja nulo
            valid_assignees = self.issues_exploded_df[
                self.issues_exploded_df["assignee"].notna() & 
                (self.issues_exploded_df["assignee"] != "")
            ]
            if not valid_assignees.empty:
                try:
                    assigned_counts = valid_assignees.groupby("assignee").size()
                except Exception as e:
                    print(f"Erro ao agrupar por assignee: {e}")
                    # Tentar método alternativo com valor_counts
                    assigned_counts = valid_assignees["assignee"].value_counts()
        
        # Combinar todos os usuários (membros das equipes, criadores de issues e assignees)
        all_users = all_members.union(set(created_counts.index)).union(set(assigned_counts.index))
        
        # Remover valores inválidos
        all_users = {user for user in all_users if user and pd.notna(user) and user != "N/A"}
        
        if not all_users:
            print("⚠️ Nenhum usuário válido encontrado para análise.")
            # Retornar DataFrame vazio mas com as colunas corretas
            return pd.DataFrame(columns=["issues_criadas", "issues_designadas", "membro_equipe"])
        
        # Criar DataFrame com as estatísticas
        stats_df = pd.DataFrame(index=sorted(all_users))
        stats_df["issues_criadas"] = created_counts
        stats_df["issues_designadas"] = assigned_counts
        stats_df.fillna(0, inplace=True)
        stats_df = stats_df.astype(int)
        
        # Adicionar coluna de membro de equipe
        stats_df["membro_equipe"] = stats_df.index.isin(all_members)
        
        # Se houver dados de equipe, adicionar a coluna de equipe
        if "team_slug" in self.members_df.columns:
            team_map = {}
            for _, row in self.members_df.iterrows():
                login = row.get("login")
                team = row.get("team_slug")
                if login and team and pd.notna(login) and pd.notna(team):
                    if login in team_map:
                        team_map[login] += f", {team}"
                    else:
                        team_map[login] = team
            
            stats_df["equipes"] = pd.Series(team_map)
        
        return stats_df
    
    def generate_markdown(self, output_path="team_issue_stats.md"):
        """Gera o relatório em markdown com as estatísticas"""
        if not self.process_data():
            print("⚠️ Não foi possível gerar o relatório devido a dados insuficientes.")
            return
        
        stats_df = self.count_issues_by_member()
        
        # Iniciar o documento markdown
        md = "# 📊 Estatísticas de Equipes e Issues\n\n"
        
        # Estatísticas gerais em forma narrativa
        md += "## 📈 Resumo Geral\n\n"
        
        total_issues = len(self.issues_df)
        total_members = len(stats_df[stats_df["membro_equipe"]])
        
        md += f"Este repositório contém **{total_issues} issues** sendo gerenciadas por **{total_members} membros** distribuídos em diferentes equipes.\n\n"
        
        # Top contribuidores em formato de lista
        top_creators = stats_df.sort_values("issues_criadas", ascending=False).head(5)
        md += "### Top Criadores de Issues\n\n"
        
        for user, row in top_creators.iterrows():
            teams = row.get("equipes", "Não especificada") if row["membro_equipe"] else "Não é membro de equipe"
            md += f"- **{user}**: {row['issues_criadas']} issues criadas, membro da(s) equipe(s): {teams}\n"
        
        md += "\n"
        
        # Top assignees em formato de lista
        top_assignees = stats_df.sort_values("issues_designadas", ascending=False).head(5)
        md += "### Top Destinatários de Issues\n\n"
        
        for user, row in top_assignees.iterrows():
            teams = row.get("equipes", "Não especificada") if row["membro_equipe"] else "Não é membro de equipe"
            md += f"- **{user}**: {row['issues_designadas']} issues designadas, membro da(s) equipe(s): {teams}\n"
        
        md += "\n"
        
        # Gráfico de top contribuidores (criadores e assignees combinados)
        if len(stats_df) > 0:
            stats_df["total"] = stats_df["issues_criadas"] + stats_df["issues_designadas"]
            top_total = stats_df.sort_values("total", ascending=False).head(10)
            
            if not top_total.empty:
                plt.figure(figsize=(12, 6))
                top_total[["issues_criadas", "issues_designadas"]].plot(
                    kind="bar", stacked=True, figsize=(12, 6),
                    color=["#5470C6", "#91CC75"]
                )
                plt.title("Top 10 Contribuidores (Issues Criadas + Designadas)")
                plt.ylabel("Número de Issues")
                plt.xlabel("Usuários")
                plt.xticks(range(len(top_total.index)), top_total.index, rotation=45, ha="right")
                plt.legend(["Issues Criadas", "Issues Designadas"])
                plt.tight_layout()
                
                buf = BytesIO()
                plt.savefig(buf, format="png", dpi=100)
                plt.close()
                buf.seek(0)
                img_base64 = base64.b64encode(buf.read()).decode("utf-8")
                md += f"![Gráfico de Top Contribuidores](data:image/png;base64,{img_base64})\n\n"
        
        # Se houver dados de equipe, adicionar estatísticas por equipe
        if "team_slug" in self.members_df.columns:
            md += "## 🏢 Análise por Equipe\n\n"
            
            # Agrupar por equipe
            team_stats = {}
            for _, row in self.members_df.iterrows():
                login = row.get("login")
                team = row.get("team_slug")
                if login and team and pd.notna(login) and pd.notna(team):
                    if team not in team_stats:
                        team_stats[team] = {"membros": [], "issues_criadas": 0, "issues_designadas": 0}
                    
                    team_stats[team]["membros"].append(login)
                    
                    # Adicionar contagem de issues se o usuário estiver nas estatísticas
                    if login in stats_df.index:
                        team_stats[team]["issues_criadas"] += stats_df.loc[login, "issues_criadas"]
                        team_stats[team]["issues_designadas"] += stats_df.loc[login, "issues_designadas"]
            
            # Criar dataframe para visualização
            team_df = pd.DataFrame({
                "equipe": list(team_stats.keys()),
                "membros": [len(data["membros"]) for data in team_stats.values()],
                "issues_criadas": [data["issues_criadas"] for data in team_stats.values()],
                "issues_designadas": [data["issues_designadas"] for data in team_stats.values()]
            })
            
            team_df["media_issues_por_membro"] = (team_df["issues_criadas"] / team_df["membros"]).round(1)
            team_df = team_df.sort_values("issues_criadas", ascending=False)
            
            # Descrição narrativa das equipes
            md += f"O repositório possui **{len(team_stats)}** equipes ativas. "
            md += f"A equipe com mais issues criadas é **{team_df.iloc[0]['equipe']}** com {team_df.iloc[0]['issues_criadas']} issues.\n\n"
            
            md += "### Resumo por Equipe\n\n"
            
            for _, row in team_df.iterrows():
                md += f"- **{row['equipe']}**: {row['membros']} membros, {row['issues_criadas']} issues criadas, "
                md += f"{row['issues_designadas']} issues designadas, média de {row['media_issues_por_membro']} issues por membro\n"
            
            md += "\n"
            
            # Gráfico de barras para visualizar as equipes
            if not team_df.empty:
                plt.figure(figsize=(12, 6))
                team_df.plot(
                    x="equipe", y=["issues_criadas", "issues_designadas"], 
                    kind="bar", figsize=(12, 6),
                    color=["#5470C6", "#91CC75"]
                )
                plt.title("Contribuição por Equipe")
                plt.ylabel("Número de Issues")
                plt.xlabel("Equipe")
                plt.xticks(rotation=45, ha="right")
                plt.legend(["Issues Criadas", "Issues Designadas"])
                plt.tight_layout()
                
                buf = BytesIO()
                plt.savefig(buf, format="png", dpi=100)
                plt.close()
                buf.seek(0)
                img_base64 = base64.b64encode(buf.read()).decode("utf-8")
                md += f"![Gráfico de Contribuição por Equipe](data:image/png;base64,{img_base64})\n\n"
            
            # Detalhes por equipe
            md += "## 📋 Perfil das Equipes\n\n"
            
            for team, data in sorted(team_stats.items()):
                md += f"### 🔍 {team}\n\n"
                
                md += f"A equipe **{team}** tem {len(data['membros'])} membros, "
                md += f"que criaram {data['issues_criadas']} issues e receberam {data['issues_designadas']} designações.\n\n"
                
                # Lista de membros e suas contribuições
                md += "**Membros e suas contribuições:**\n\n"
                
                members_data = []
                for member in sorted(data["membros"]):
                    if member in stats_df.index:
                        created = stats_df.loc[member, "issues_criadas"]
                        assigned = stats_df.loc[member, "issues_designadas"]
                        md += f"- **{member}**: {created} issues criadas, {assigned} issues designadas\n"
                        members_data.append({
                            "membro": member,
                            "criadas": created,
                            "designadas": assigned
                        })
                    else:
                        md += f"- **{member}**: 0 issues criadas, 0 issues designadas\n"
                
                md += "\n"
                
                # Gráfico de issues por membro da equipe
                if members_data:
                    members_df = pd.DataFrame(members_data)
                    if not members_df.empty and members_df["criadas"].sum() > 0:
                        plt.figure(figsize=(12, 5))
                        members_df.plot(
                            x="membro", y=["criadas", "designadas"], 
                            kind="bar", figsize=(12, 5),
                            color=["#5470C6", "#91CC75"]
                        )
                        plt.title(f"Contribuição dos Membros - {team}")
                        plt.ylabel("Número de Issues")
                        plt.xlabel("Membro")
                        plt.xticks(rotation=45, ha="right")
                        plt.legend(["Issues Criadas", "Issues Designadas"])
                        plt.tight_layout()
                        
                        buf = BytesIO()
                        plt.savefig(buf, format="png", dpi=100)
                        plt.close()
                        buf.seek(0)
                        img_base64 = base64.b64encode(buf.read()).decode("utf-8")
                        md += f"![Contribuição dos Membros](data:image/png;base64,{img_base64})\n\n"
                
                md += "---\n\n"
        
        
    
    def run(self):
        """Executa todo o processo"""
        self.fetch_data()
        md = self.generate_markdown()
        self.save_func(self.report_dir, "team_issue_stats.md",md)