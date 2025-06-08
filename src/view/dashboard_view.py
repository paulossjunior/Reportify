import os
import webbrowser

class DashboardView:
    def __init__(self, report_dir):
        self.report_dir = report_dir

    def render_markdown_viewer(self):
        # Lista os arquivos .md no diretório do relatório
        md_files = [f for f in os.listdir(self.report_dir) if f.endswith('.md')]
        if not md_files:
            print("Nenhum arquivo Markdown encontrado.")
            return

        # Cria botões para cada MD (abas)
        tabs = "\n".join([
            f'<button class="tablink" onclick="loadMarkdown(\'{fname}\')">{fname}</button>'
            for fname in md_files
        ])

        # HTML com JavaScript para carregar .md dinamicamente
        html_content = f"""
        <!DOCTYPE html>
        <html lang="pt-BR">
        <head>
        <meta charset="UTF-8">
        <title>Relatórios</title>
        <script src="https://cdn.jsdelivr.net/npm/markdown-it@13.0.1/dist/markdown-it.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/markdown-it-gfm@1.0.0-beta.1/dist/markdown-it-gfm.min.js"></script>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; }}
            .tablink {{ margin-right: 10px; padding: 10px; background: #f2f2f2; border: none; cursor: pointer; }}
            .tablink:hover {{ background-color: #ddd; }}
            table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
            th, td {{ border: 1px solid #ccc; padding: 8px; text-align: center; }}
            th {{ background-color: #f5f5f5; }}
            img {{ max-width: 100%; margin-top: 20px; }}
        </style>
        </head>
        <body>
        <h1>📊 Relatórios</h1>
        <div>{tabs}</div>
        <div id="content">Selecione um relatório acima</div>

        <script>
            const md = window.markdownit({{ html: true }}).use(window.markdownitGfm);
            function loadMarkdown(file) {{
            fetch(file)
                .then(response => response.text())
                .then(text => {{
                document.getElementById('content').innerHTML = md.render(text);
                }});
            }}
        </script>
        </body>
        </html>
        """


        # Salva o arquivo HTML dentro do report_dir
        output_path = os.path.join(self.report_dir, "index.html")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        print(f"✅ Visualização criada: {output_path}")
        webbrowser.open("file://" + os.path.abspath(output_path))
