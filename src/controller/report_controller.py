from model.dashboard.dashboard_developer import DeveloperStats
from model.dashboard.dashboard_organization import OrganizationalDashboard
from model.dashboard.dashboard_repository import GitHubIssueStats
from model.dashboard.dashboard_team import TeamStats
from model.dashboard.dashboard_team_graph import CollaborationGraph

class ReportController:
    def __init__(self, salvar_markdown, report_dir):
        self.save_func = salvar_markdown
        self.report_dir = report_dir

    def gerar_todos(self):
        DeveloperStats(save_func=self.save_func, save_directory=self.report_dir).run()
        OrganizationalDashboard(save_func=self.save_func, report_dir=self.report_dir).run()
        GitHubIssueStats(save_func=self.save_func, report_dir=self.report_dir).run()
        #TeamStats(save_func=self.save_func, report_dir=self.report_dir).run()
        #CollaborationGraph(save_func=self.save_func, report_dir=self.report_dir).run()
    def open_view(self):
        from view.dashboard_view import DashboardView
        view = DashboardView(self.report_dir)
        view.render_markdown_viewer()
        print(f"📂 Relatório aberto em: {self.report_dir}/index.html")