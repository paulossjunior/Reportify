import os
import airbyte as ab
import pandas as pd
import matplotlib.pyplot as plt
import base64
from io import BytesIO
from dotenv import load_dotenv
import json

class DeveloperStats:
    def __init__(self):
        load_dotenv()
        self.token = os.getenv("GITHUB_TOKEN")
        self.repository = os.getenv("GITHUB_REPOSITORY")  # Ex: 'leds-conectafapes/planner'
        if not self.token or not self.repository:
            raise ValueError("Configure GITHUB_TOKEN e GITHUB_REPOSITORY no .env")
        self.cache = ab.get_default_cache()
        self.issues_df = pd.DataFrame()
    
    def fetch_issues(self):
        print("🔄 Conectando ao GitHub e carregando issues...")
        source = ab.get_source(
            "source-github",
            install_if_missing=True,
            config={
                "repositories": [self.repository],
                "credentials": {"personal_access_token": self.token},
            }
        )
        source.check()
        source.select_streams(["issues"])
        source.read(cache=self.cache)
        if "issues" in self.cache:
            self.issues_df = self.cache["issues"].to_pandas()
            print(f"✅ {len(self.issues_df)} issues carregadas.")
        else:
            print("⚠️ Nenhuma issue encontrada.")
            self.issues_df = pd.DataFrame()
    
    def generate_markdown(self, output_path="developer_stats.md"):
        if self.issues_df.empty:
            print("⚠️ Nenhuma issue para processar.")
            return

        def extract_login(user_json):
            try:
                user = json.loads(user_json) if isinstance(user_json, str) else user_json
                return user.get("login", "N/A")
            except Exception as e:
                print(f"Erro ao extrair login: {e}")
                print(f"Valor recebido: {user_json}")
                return "N/A"

        self.issues_df["author"] = self.issues_df["user"].apply(extract_login)

        # Estatísticas por status
        status_counts = self.issues_df.groupby(["author", "state"]).size().unstack(fill_value=0)
        total_counts = self.issues_df.groupby("author").size()
        status_percent = status_counts.div(total_counts, axis=0).multiply(100).round(1)

        md = "# 📊 Estatísticas por Desenvolvedor\n\n"
        md += "## 📌 Resumo por Autor e Status\n\n"

        columns = ['Autor', 'Total'] + [f"{status.title()} (%)" for status in status_counts.columns]
        md += "| " + " | ".join(columns) + " |\n"
        md += "| " + " | ".join(["-" * len(col) for col in columns]) + " |\n"

        for author in total_counts.index:
            row = [author, total_counts[author]]
            for status in status_counts.columns:
                count = status_counts.loc[author, status]
                percent = status_percent.loc[author, status]
                row.append(f"{count} ({percent}%)")
            md += "| " + " | ".join(str(x) for x in row) + " |\n"

        md += "\n---\n\n"

        # Converter campos de data antes de agrupar
        self.issues_df["created_at"] = pd.to_datetime(self.issues_df["created_at"])
        self.issues_df["closed_at"] = pd.to_datetime(self.issues_df["closed_at"], errors='coerce')
        
        # Criar campos de período
        self.issues_df["created_period"] = self.issues_df["created_at"].dt.to_period("2W").dt.start_time
        self.issues_df["closed_period"] = self.issues_df["closed_at"].dt.to_period("2W").dt.start_time

        grouped = self.issues_df.groupby("author")
        for author, group in grouped:
            md += f"## 👤 {author}\n\n"

            # Calcular contagens por período
            created_counts = group.groupby("created_period").size()
            # Filtrar valores NaN do closed_period antes de agrupar
            valid_closed = group.dropna(subset=["closed_period"])
            closed_counts = valid_closed.groupby("closed_period").size()

            # Tabela Prometido x Realizado
            throughput_df = pd.DataFrame({
                "Prometido (Criadas)": created_counts
            }).fillna(0)
            
            # Adicionar coluna de realizados apenas se houver dados
            if not closed_counts.empty:
                throughput_df["Realizado (Fechadas)"] = pd.Series(closed_counts)
            else:
                throughput_df["Realizado (Fechadas)"] = 0
                
            throughput_df = throughput_df.fillna(0).astype(int).sort_index()

            md += "### 📊 Prometido vs Realizado (quinzenal)\n\n"
            md += "| Período | Prometido | Realizado |\n"
            md += "|---------|-----------|-----------|\n"
            for period, row_t in throughput_df.iterrows():
                md += f"| {period.date()} | {row_t['Prometido (Criadas)']} | {row_t['Realizado (Fechadas)']} |\n"
            md += "\n"

            # Gráfico Prometido vs Realizado
            plt.figure(figsize=(8, 3))
            throughput_df.plot(kind='bar')
            plt.title(f"📊 Prometido vs Realizado - {author}")
            plt.ylabel("Issues")
            plt.xlabel("Período")
            plt.xticks(range(len(throughput_df.index)), 
                       [d.strftime('%Y-%m-%d') for d in throughput_df.index], 
                       rotation=45, ha='right')
            plt.tight_layout()

            buf = BytesIO()
            plt.savefig(buf, format="png")
            plt.close()
            buf.seek(0)
            img_base64 = base64.b64encode(buf.read()).decode("utf-8")
            md += f"![Gráfico Prometido vs Realizado](data:image/png;base64,{img_base64})\n\n"

            # Gráfico de Throughput (fechadas)
            # Usar valores filtrados sem NaN para o throughput
            md += "### 📈 Throughput (Issues Fechadas)\n\n"
            
            if not valid_closed.empty:
                throughput = valid_closed.groupby("closed_period").size().sort_index()
                
                plt.figure(figsize=(8, 3))
                throughput.plot(kind='line', marker='o')
                plt.title(f"📈 Throughput Quinzenal - {author}")
                plt.ylabel("Issues Fechadas")
                plt.xlabel("Período")
                plt.xticks(range(len(throughput.index)), 
                           [d.strftime('%Y-%m-%d') for d in throughput.index], 
                           rotation=45, ha='right')
                plt.tight_layout()

                buf2 = BytesIO()
                plt.savefig(buf2, format="png")
                plt.close()
                buf2.seek(0)
                img_base64_2 = base64.b64encode(buf2.read()).decode("utf-8")
                md += f"![Gráfico de Throughput](data:image/png;base64,{img_base64_2})\n\n"
            else:
                md += "_Nenhum dado de throughput disponível (nenhuma issue foi fechada)._\n\n"

            # Tabela de issues
            md += "### 📋 Issues\n\n"
            md += "| Número | Título | Estado | Criado em | URL | Assignee |\n"
            md += "|--------|--------|--------|-----------|-----|----------|\n"

            for _, row in group.iterrows():
                created_str = row['created_at'].strftime('%Y-%m-%d') if pd.notna(row['created_at']) else ''
                assignee = 'N/A'
                try:
                    if pd.notna(row['assignee']):
                        a_obj = json.loads(row['assignee']) if isinstance(row['assignee'], str) else row['assignee']
                        assignee = a_obj.get("login", "N/A")
                    
                    if pd.notna(row['assignees']):
                        a_list = json.loads(row['assignees']) if isinstance(row['assignees'], str) else row['assignees']
                        login_list = []
                        for a in a_list:
                            login = a.get("login", "")
                            if login:
                                login_list.append(login)
                        if login_list:
                            assignee = ", ".join(login_list)
                except Exception as e:
                    print(f"Erro ao processar assignees: {e}")

                md += (
                    f"| {row['number']} | {row['title']} | {row['state']} | "
                    f"{created_str} | [Link]({row['html_url']}) | {assignee} |\n"
                )

            md += "\n---\n\n"

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(md)

        print(f"📄 Markdown gerado em: {output_path}")
    
    def run(self):
        self.fetch_issues()
        self.generate_markdown()