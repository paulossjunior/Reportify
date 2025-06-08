import os
import shutil
from datetime import datetime

from dashboard.dashboard_organization import OrganizationalDashboard
from dashboard.dashboard_developer import DeveloperStats
from dashboard.dashboard_repository import GitHubIssueStats
from dashboard.dashboard_team_graph import CollaborationGraph
from dashboard.dashboard_team import TeamStats


class Report:
    def __init__(self):
        self.base_dir = "organization_charts"
        os.makedirs(self.base_dir, exist_ok=True)
        os.makedirs('Reports', exist_ok=True)

        now = datetime.now()
        self.timestamp = f"Report{now.day:02}{now.month:02}{now.year}-{now.hour:02}h:{now.minute:02}min"
        self.report_dir = os.path.join("Reports", self.timestamp)

    def salvar_markdown(self, save_directory: str, file_name: str, md: str):
        os.makedirs(save_directory, exist_ok=True)
        caminho_arquivo = os.path.join(save_directory, file_name)

        with open(caminho_arquivo, "w", encoding="utf-8") as f:
            f.write(md)

        print(f"📄 Markdown gerado em: {caminho_arquivo}")

    def generate(self):
        print(f"📊 Gerando relatório em: {self.report_dir}")

        
        #DeveloperStats(save_func=self.salvar_markdown, save_directory=self.report_dir).run()
        #OrganizationalDashboard(save_func=self.salvar_markdown, report_dir=self.report_dir).run()
        #GitHubIssueStats(save_func=self.salvar_markdown, report_dir=self.report_dir).run()
        TeamStats().run()
        #CollaborationGraph().run()

        # Remove cache
        if os.path.exists('.cache'):
            shutil.rmtree('.cache')
            print("🧹 Diretório .cache removido.")


if __name__ == "__main__":
    report = Report()
    report.generate()
