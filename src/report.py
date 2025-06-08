from controller.report_controller import ReportController
from datetime import datetime
import os, shutil

class Report:
    def __init__(self):
        now = datetime.now()
        self.report_dir = os.path.join("Reports", f"Report{now.day:02}{now.month:02}{now.year}-{now.hour:02}h:{now.minute:02}min")
        os.makedirs(self.report_dir, exist_ok=True)

    def salvar_markdown(self, save_directory, filename, content):
        os.makedirs(save_directory, exist_ok=True)
        path = os.path.join(save_directory, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"📄 Markdown salvo em: {path}")

    def gerar(self):
        controller = ReportController(self.salvar_markdown, self.report_dir)
        controller.gerar_todos()
        controller.open_view()  
        print(f"📂 Relatório completo em: {self.report_dir}")
        
        if os.path.exists(".cache"):
            shutil.rmtree(".cache")
            print("🧹 Cache removido.")

if __name__ == "__main__":
    Report().gerar()
    