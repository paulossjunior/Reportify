import os
import json
import pandas as pd
import networkx as nx
import matplotlib.pyplot as plt
import plotly.graph_objects as go
from plotly.offline import plot
import airbyte as ab
from dotenv import load_dotenv
import numpy as np
from collections import defaultdict
# Removida dependência do community (python-louvain)


class CollaborationGraph:
    def __init__(self,save_func,report_dir):
        load_dotenv()
        self.token = os.getenv("GITHUB_TOKEN")
        self.repository = os.getenv("GITHUB_REPOSITORY")
        self.save_func = save_func
        self.report_dir = report_dir
        if not self.token or not self.repository:
            raise ValueError("Configure GITHUB_TOKEN e GITHUB_REPOSITORY no .env")
        
        self.cache = ab.get_default_cache()
        self.issues_df = pd.DataFrame()
        self.graph = nx.DiGraph()
        self.undirected_graph = nx.Graph()  # Para análises que precisam de grafo não direcionado

    def fetch_issues(self):
        print("🔄 Buscando issues do GitHub via Airbyte...")
        source = ab.get_source(
            "source-github",
            install_if_missing=True,
            config={
                "repositories": [self.repository],
                "credentials": {"personal_access_token": self.token},
            },
        )
        source.check()
        source.select_streams(["issues"])
        source.read(cache=self.cache)

        if "issues" in self.cache:
            df = self.cache["issues"].to_pandas()
            df["author"] = df["user"].apply(
                lambda u: json.loads(u)["login"] if isinstance(u, str) else u.get("login", "N/A")
            )
            self.issues_df = df
            print(f"✅ {len(self.issues_df)} issues carregadas.")
        else:
            print("⚠️ Nenhuma issue encontrada.")
            self.issues_df = pd.DataFrame()

    def build(self):
        for _, row in self.issues_df.iterrows():
            try:
                author = row["author"]
                assignees = []

                if pd.notna(row["assignee"]):
                    a_obj = json.loads(row["assignee"]) if isinstance(row["assignee"], str) else row["assignee"]
                    assignees.append(a_obj.get("login", ""))

                if pd.notna(row["assignees"]):
                    a_list = json.loads(row["assignees"]) if isinstance(row["assignees"], str) else row["assignees"]
                    for a in a_list:
                        login = a.get("login", "")
                        if login:
                            assignees.append(login)

                for assignee in assignees:
                    if assignee and assignee != author:
                        if self.graph.has_edge(author, assignee):
                            self.graph[author][assignee]['weight'] += 1
                        else:
                            self.graph.add_edge(author, assignee, weight=1)
            except Exception as e:
                print(f"Erro ao processar author/assignee: {e}")
        
        # Criar também a versão não direcionada do grafo para algumas métricas
        self.undirected_graph = self.graph.to_undirected()

    def identify_hubs(self, top_n=5):
        """
        Identifica os hubs da rede usando diferentes métricas de centralidade.
        """
        # Centralidade de grau (número de conexões)
        degree_centrality = nx.degree_centrality(self.graph)
        
        # Centralidade de intermediação (quanto um nó está no caminho entre outros nós)
        betweenness_centrality = nx.betweenness_centrality(self.graph)
        
        # Centralidade de proximidade (quão próximo um nó está de todos os outros)
        # Usamos o grafo não direcionado para garantir que todos os nós sejam acessíveis
        closeness_centrality = nx.closeness_centrality(self.undirected_graph)
        
        # Centralidade de autovetor - modificada para lidar com grafos desconexos
        # Usamos try/except para capturar a exceção AmbiguousSolution
        try:
            eigenvector_centrality = nx.eigenvector_centrality_numpy(self.undirected_graph, weight='weight')
        except (nx.NetworkXError, nx.AmbiguousSolution):
            print("⚠️ Não foi possível calcular a centralidade de autovetor para um grafo desconexo. Usando alternativa.")
            # Alternativa: calcular para cada componente conexa separadamente
            eigenvector_centrality = {}
            for component in nx.connected_components(self.undirected_graph):
                if len(component) > 1:  # Precisamos de pelo menos 2 nós
                    subgraph = self.undirected_graph.subgraph(component)
                    try:
                        ec = nx.eigenvector_centrality_numpy(subgraph, weight='weight')
                        eigenvector_centrality.update(ec)
                    except:
                        # Para componentes problemáticos, usamos centralidade de grau como fallback
                        for node in component:
                            eigenvector_centrality[node] = degree_centrality[node]
                else:
                    # Para nós isolados, definimos um valor baixo
                    for node in component:
                        eigenvector_centrality[node] = 0.01
        
        # Ordenar os nós por cada métrica
        top_degree = sorted(degree_centrality.items(), key=lambda x: x[1], reverse=True)[:top_n]
        top_betweenness = sorted(betweenness_centrality.items(), key=lambda x: x[1], reverse=True)[:top_n]
        top_closeness = sorted(closeness_centrality.items(), key=lambda x: x[1], reverse=True)[:top_n]
        top_eigenvector = sorted(eigenvector_centrality.items(), key=lambda x: x[1], reverse=True)[:top_n]
        
        return {
            'degree': top_degree,
            'betweenness': top_betweenness,
            'closeness': top_closeness,
            'eigenvector': top_eigenvector
        }
    
    def analyze_communication_distance(self):
        """
        Analisa as distâncias de comunicação na rede.
        """
        # Calcular a distância média entre todos os pares de nós
        # Usamos o grafo não direcionado para garantir que todos os nós sejam acessíveis
        try:
            avg_shortest_path = nx.average_shortest_path_length(self.undirected_graph)
        except nx.NetworkXError:
            # Se o grafo não for conexo, calcular para cada componente conexa
            components = list(nx.connected_components(self.undirected_graph))
            avg_paths = []
            for component in components:
                if len(component) > 1:  # Precisamos de pelo menos 2 nós para calcular caminhos
                    subgraph = self.undirected_graph.subgraph(component)
                    avg_paths.append(nx.average_shortest_path_length(subgraph))
            
            avg_shortest_path = np.mean(avg_paths) if avg_paths else float('inf')
        
        # Calcular o diâmetro (maior distância entre quaisquer dois nós)
        # Novamente, para grafos desconexos, calculamos para cada componente
        try:
            diameter = nx.diameter(self.undirected_graph)
        except nx.NetworkXError:
            diameter_values = []
            for component in nx.connected_components(self.undirected_graph):
                if len(component) > 1:
                    subgraph = self.undirected_graph.subgraph(component)
                    diameter_values.append(nx.diameter(subgraph))
            
            diameter = max(diameter_values) if diameter_values else float('inf')
        
        # Calcular a eficiência global (média do inverso das distâncias mais curtas)
        efficiency = nx.global_efficiency(self.undirected_graph)
        
        return {
            'avg_shortest_path': avg_shortest_path,
            'diameter': diameter,
            'efficiency': efficiency
        }
    
    def analyze_small_world_effect(self):
        """
        Analisa se a rede apresenta o efeito de mundo pequeno.
        
        Um grafo de mundo pequeno tem:
        1. Distância média pequena entre os nós
        2. Alto coeficiente de clustering
        
        Comparamos com grafos aleatórios de mesmo tamanho e densidade.
        """
        # Calcular o coeficiente de clustering
        clustering_coefficient = nx.average_clustering(self.undirected_graph)
        
        # Criar um grafo aleatório de Erdős-Rényi com o mesmo número de nós e arestas
        n = self.undirected_graph.number_of_nodes()
        m = self.undirected_graph.number_of_edges()
        p = (2 * m) / (n * (n - 1)) if n > 1 else 0
        
        # Gerar vários grafos aleatórios e tirar a média das métricas
        num_random_graphs = 10
        random_clustering = 0
        random_path_length = 0
        
        for _ in range(num_random_graphs):
            random_graph = nx.gnp_random_graph(n, p)
            if nx.is_connected(random_graph) and n > 1:
                random_clustering += nx.average_clustering(random_graph)
                random_path_length += nx.average_shortest_path_length(random_graph)
        
        if num_random_graphs > 0:
            random_clustering /= num_random_graphs
            random_path_length /= num_random_graphs
        
        # Calcular a distância média no grafo real (se possível)
        try:
            real_path_length = nx.average_shortest_path_length(self.undirected_graph)
        except nx.NetworkXError:
            # Grafo não conexo
            components = list(nx.connected_components(self.undirected_graph))
            avg_paths = []
            for component in components:
                if len(component) > 1:
                    subgraph = self.undirected_graph.subgraph(component)
                    avg_paths.append(nx.average_shortest_path_length(subgraph))
            
            real_path_length = np.mean(avg_paths) if avg_paths else float('inf')
        
        # Calcular o índice sigma de mundo pequeno
        # Um valor sigma >> 1 indica efeito de mundo pequeno
        sigma = (clustering_coefficient / random_clustering) / (real_path_length / random_path_length) if random_clustering > 0 and random_path_length > 0 else 0
        
        return {
            'clustering_coefficient': clustering_coefficient,
            'random_clustering': random_clustering,
            'real_path_length': real_path_length,
            'random_path_length': random_path_length,
            'sigma': sigma,
            'is_small_world': sigma > 1
        }
    
    def detect_communities(self):
        """
        Detecta comunidades na rede usando algoritmos disponíveis no NetworkX.
        """
        # Converter o grafo para não direcionado para detecção de comunidades
        undirected = self.graph.to_undirected()
        
        # Usar o algoritmo Greedy Modularity Maximization do NetworkX
        communities_generator = nx.algorithms.community.greedy_modularity_communities(undirected)
        communities = list(communities_generator)
        
        # Organizar os nós por comunidade
        communities_dict = {}
        partition = {}
        
        for i, community in enumerate(communities):
            communities_dict[i] = list(community)
            for node in community:
                partition[node] = i
        
        # Calcular a modularidade
        modularity = nx.algorithms.community.modularity(undirected, communities)
        
        return {
            'partition': partition,
            'communities': communities_dict,
            'modularity': modularity
        }

    def generate_markdown(self, output_path="collaboration_report.md"):
        md = "# 🤝 Relatório de Colaboração entre Desenvolvedores\n\n"
        md += "Este relatório analisa o padrão de colaboração entre desenvolvedores através das issues do GitHub, utilizando conceitos de redes complexas para identificar estruturas importantes na equipe.\n\n"

        # Seção introdutória explicando o grafo
        md += "## 📊 O Grafo de Colaboração\n\n"
        md += "Um grafo de colaboração representa as interações entre desenvolvedores como uma rede:\n\n"
        md += "- Cada **nó** representa um desenvolvedor\n"
        md += "- Cada **aresta** representa uma colaboração via issue (do autor para o assignee)\n"
        md += "- O **peso** da aresta indica quantas vezes essa colaboração ocorreu\n\n"
        
        md += f"Nosso grafo contém **{self.graph.number_of_nodes()} desenvolvedores** e **{self.graph.number_of_edges()} colaborações** entre eles.\n\n"
        
        try:
            # Verificar se o grafo é conexo
            is_connected = nx.is_strongly_connected(self.graph)
            if is_connected:
                md += "O grafo é **conexo**, o que significa que existe um caminho entre qualquer par de desenvolvedores.\n\n"
            else:
                components = list(nx.weakly_connected_components(self.graph))
                md += f"O grafo é **desconexo**, contendo **{len(components)} componentes** separadas. Isso indica que existem grupos isolados de desenvolvedores que não colaboram entre si.\n\n"
        except Exception as e:
            md += "Não foi possível determinar se o grafo é conexo.\n\n"
        
        # Seção de análise de redes complexas
        md += "## 🔬 Análise de Redes Complexas\n\n"
        
        # ---- HUBS ----
        md += "### 🌟 Hubs: Os Desenvolvedores Centrais\n\n"
        md += "**Hubs** são nós com importância especial na rede. No contexto de desenvolvimento de software, identificar hubs ajuda a reconhecer os desenvolvedores que têm papéis cruciais na colaboração da equipe.\n\n"
        
        hubs = self.identify_hubs()
        
        md += "#### Centralidade de Grau\n\n"
        md += "A **centralidade de grau** mede quantas conexões diretas um desenvolvedor possui. Desenvolvedores com alta centralidade de grau colaboram com muitas pessoas diferentes.\n\n"
        md += "| Desenvolvedor | Centralidade | Significado |\n"
        md += "|---------------|-------------|-------------|\n"
        for node, centrality in hubs['degree']:
            md += f"| {node} | {centrality:.4f} | Colabora diretamente com {int(centrality * (self.graph.number_of_nodes() - 1))} desenvolvedores |\n"
        md += "\n"
        
        md += "#### Centralidade de Intermediação\n\n"
        md += "A **centralidade de intermediação** identifica desenvolvedores que servem como 'pontes' entre diferentes grupos. Desenvolvedores com alta intermediação frequentemente conectam equipes diferentes e facilitam a comunicação entre grupos que, de outra forma, estariam isolados.\n\n"
        md += "| Desenvolvedor | Centralidade | Interpretação |\n"
        md += "|---------------|-------------|-------------|\n"
        for node, centrality in hubs['betweenness']:
            interpretation = "Papel crítico como conector entre equipes" if centrality > 0.3 else "Conecta alguns grupos diferentes" if centrality > 0.1 else "Pouco papel como intermediário"
            md += f"| {node} | {centrality:.4f} | {interpretation} |\n"
        md += "\n"
        
        md += "#### Centralidade de Proximidade\n\n"
        md += "A **centralidade de proximidade** mede quão perto um desenvolvedor está de todos os outros na rede. Desenvolvedores com alta proximidade podem disseminar informações rapidamente para toda a equipe.\n\n"
        md += "| Desenvolvedor | Centralidade | Interpretação |\n"
        md += "|---------------|-------------|-------------|\n"
        for node, centrality in hubs['closeness']:
            if centrality > 0:
                avg_distance = 1/centrality if centrality > 0 else float('inf')
                interpretation = f"Em média, alcança outros em {avg_distance:.1f} passos"
            else:
                interpretation = "Isolado ou em componente desconectado"
            md += f"| {node} | {centrality:.4f} | {interpretation} |\n"
        md += "\n"
        
        md += "#### Centralidade de Autovetor\n\n"
        md += "A **centralidade de autovetor** mede a influência de um desenvolvedor baseada na importância de seus colaboradores. Um desenvolvedor com alta centralidade de autovetor colabora com outros desenvolvedores centrais.\n\n"
        md += "| Desenvolvedor | Centralidade | Interpretação |\n"
        md += "|---------------|-------------|-------------|\n"
        for node, centrality in hubs['eigenvector']:
            interpretation = "Colabora com outros desenvolvedores altamente centrais" if centrality > 0.5 else "Colabora com desenvolvedores de média influência" if centrality > 0.2 else "Colabora principalmente com desenvolvedores periféricos"
            md += f"| {node} | {centrality:.4f} | {interpretation} |\n"
        md += "\n"
        
        # ---- DISTÂNCIA DE COMUNICAÇÃO ----
        md += "### 🔄 Distância de Comunicação\n\n"
        md += "A **distância de comunicação** mede quão eficientemente a informação pode fluir na rede de colaboração. Distâncias menores indicam comunicação mais rápida e eficiente.\n\n"
        
        distance = self.analyze_communication_distance()
        md += f"- **Distância Média**: {distance['avg_shortest_path']:.2f} passos\n"
        
        if distance['avg_shortest_path'] < 2:
            md += "  - *Interpretação*: Comunicação muito eficiente, com a maioria dos desenvolvedores colaborando diretamente\n"
        elif distance['avg_shortest_path'] < 3:
            md += "  - *Interpretação*: Boa comunicação, geralmente com apenas um intermediário\n"
        elif distance['avg_shortest_path'] < 4:
            md += "  - *Interpretação*: Comunicação moderada, frequentemente necessitando vários intermediários\n"
        else:
            md += "  - *Interpretação*: Comunicação potencialmente lenta, com muitos intermediários necessários\n"
        
        md += f"\n- **Diâmetro da Rede**: {distance['diameter']} passos\n"
        md += f"  - *Interpretação*: A maior distância entre quaisquer dois desenvolvedores. Um diâmetro de {distance['diameter']} significa que são necessários no máximo {distance['diameter']} passos para uma informação ir de um desenvolvedor para qualquer outro.\n"
        
        md += f"\n- **Eficiência Global**: {distance['efficiency']:.4f}\n"
        if distance['efficiency'] > 0.7:
            md += "  - *Interpretação*: Rede altamente eficiente para troca de informações\n"
        elif distance['efficiency'] > 0.4:
            md += "  - *Interpretação*: Eficiência moderada na troca de informações\n"
        else:
            md += "  - *Interpretação*: Rede com baixa eficiência para troca de informações\n\n"
        
        # ---- EFEITO DE MUNDO PEQUENO ----
        md += "### 🌐 Efeito de Mundo Pequeno\n\n"
        md += "O **efeito de mundo pequeno** é um fenômeno onde, apesar do grande tamanho da rede, a distância entre quaisquer dois nós permanece pequena. Redes de mundo pequeno combinam duas características:\n\n"
        md += "1. **Alto agrupamento local**: Desenvolvedores formam grupos coesos onde todos colaboram entre si\n"
        md += "2. **Baixa distância global**: A informação pode se mover rapidamente de qualquer desenvolvedor para outro\n\n"
        
        small_world = self.analyze_small_world_effect()
        
        md += "#### Comparação com Redes Aleatórias\n\n"
        md += "Para determinar se uma rede tem o efeito de mundo pequeno, comparamos suas propriedades com redes aleatórias equivalentes:\n\n"
        
        md += "| Métrica | Nossa Rede | Rede Aleatória | Razão | Interpretação |\n"
        md += "|---------|-----------|---------------|-------|---------------|\n"
        c_ratio = small_world['clustering_coefficient']/small_world['random_clustering'] if small_world['random_clustering'] > 0 else 'N/A'
        l_ratio = small_world['real_path_length']/small_world['random_path_length'] if small_world['random_path_length'] > 0 else 'N/A'
        
        c_interpret = "Muito maior (favorece mundo pequeno)" if isinstance(c_ratio, str) or c_ratio > 3 else "Maior (favorece mundo pequeno)" if c_ratio > 1 else "Menor (desfavorece mundo pequeno)"
        l_interpret = "Similar (favorece mundo pequeno)" if isinstance(l_ratio, str) or (l_ratio > 0.7 and l_ratio < 1.3) else "Muito diferente (desfavorece mundo pequeno)"
        
        md += f"| Coeficiente de Clustering | {small_world['clustering_coefficient']:.4f} | {small_world['random_clustering']:.4f} | {c_ratio if isinstance(c_ratio, str) else f'{c_ratio:.2f}'} | {c_interpret} |\n"
        md += f"| Distância Média | {small_world['real_path_length']:.4f} | {small_world['random_path_length']:.4f} | {l_ratio if isinstance(l_ratio, str) else f'{l_ratio:.2f}'} | {l_interpret} |\n"
        
        md += "\n#### Índice σ de Mundo Pequeno\n\n"
        md += "O **índice σ** combina as duas métricas acima para quantificar o efeito de mundo pequeno. Um valor σ > 1 indica presença do efeito.\n\n"
        
        is_small_world = "✅ SIM" if small_world['is_small_world'] else "❌ NÃO"
        md += f"- **Efeito de Mundo Pequeno**: {is_small_world} (σ = {small_world['sigma']:.4f})\n\n"
        
        if small_world['is_small_world']:
            md += "**Implicações para a equipe**: A colaboração possui uma estrutura eficiente, onde desenvolvedores formam grupos de trabalho coesos, mas ainda conseguem se comunicar rapidamente com qualquer outro membro da equipe.\n\n"
        else:
            md += "**Implicações para a equipe**: A colaboração não possui uma estrutura ideal de 'mundo pequeno'. Isso pode indicar:\n"
            md += "- Grupos muito isolados sem conexões entre si\n"
            md += "- Estrutura hierárquica rígida em vez de colaboração flexível\n"
            md += "- Possível oportunidade para melhorar a estrutura de colaboração\n\n"
        
        # ---- COMUNIDADES ----
        try:
            communities = self.detect_communities()
            md += "### 👥 Comunidades de Desenvolvedores\n\n"
            md += "**Comunidades** são grupos de desenvolvedores que colaboram mais intensamente entre si do que com o resto da equipe. A detecção de comunidades revela a estrutura natural dos grupos de trabalho.\n\n"
            
            md += f"- **Modularidade**: {communities['modularity']:.4f}\n"
            if communities['modularity'] > 0.7:
                md += "  - *Interpretação*: Comunidades muito bem definidas e separadas\n"
            elif communities['modularity'] > 0.3:
                md += "  - *Interpretação*: Comunidades moderadamente definidas\n"
            else:
                md += "  - *Interpretação*: Comunidades fracamente definidas, com muita colaboração entre grupos\n"
                
            md += f"\n- **Número de Comunidades**: {len(communities['communities'])}\n\n"
            
            # Encontrar os desenvolvedores mais centrais em cada comunidade
            md += "#### Estrutura das Comunidades\n\n"
            for community_id, members in communities['communities'].items():
                if members:  # Verificar se há membros na comunidade
                    md += f"##### Comunidade {community_id + 1}\n\n"
                    
                    # Subgrafo apenas com membros desta comunidade
                    subgraph = self.graph.subgraph(members)
                    
                    # Encontrar o desenvolvedor mais central na comunidade (por grau)
                    central_members = sorted([(node, subgraph.degree(node)) for node in subgraph.nodes()], 
                                            key=lambda x: x[1], reverse=True)
                    
                    # Descrição da comunidade
                    md += f"Esta comunidade contém **{len(members)} desenvolvedores** com **{subgraph.number_of_edges()} colaborações** internas.\n\n"
                    
                    # Membros mais centrais
                    if central_members:
                        md += "**Membros mais centrais:**\n\n"
                        md += "| Desenvolvedor | Conexões internas |\n"
                        md += "|---------------|-------------------|\n"
                        for member, degree in central_members[:min(3, len(central_members))]:
                            md += f"| {member} | {degree} |\n"
                        md += "\n"
                    
                    # Lista completa de membros
                    md += "**Todos os membros:**\n\n"
                    md += "| Membro |\n"
                    md += "|--------|\n"
                    for member in sorted(members):
                        md += f"| {member} |\n"
                    md += "\n"
        except Exception as e:
            md += "### 👥 Comunidades de Desenvolvedores\n\n"
            md += f"Não foi possível detectar comunidades: {str(e)}\n\n"
        
        # Seção de visualizações
        md += "## 📊 Visualizações\n\n"
        
        md += "### 🖼️ Grafo Ponderado por Interações\n\n"
        md += "Esta visualização destaca as características principais da rede:\n\n"
        md += "- **Tamanho dos nós**: Representa a centralidade de grau (quanto maior, mais conexões)\n"
        md += "- **Cor dos nós**: Representa a centralidade de intermediação (quanto mais escuro, mais o desenvolvedor serve como ponte)\n"
        md += "- **Espessura das arestas**: Representa a intensidade da colaboração (quantas issues em comum)\n\n"
        
        md += "![Grafo de Colaboração](collaboration_graph_weighted.png)\n\n"
        
        md += "### 🌈 Comunidades Detectadas\n\n"
        md += "Esta visualização mostra as comunidades naturais de colaboração, com cores diferentes para cada grupo:\n\n"
        md += "![Comunidades de Desenvolvedores](collaboration_graph_communities.png)\n\n"
        
        md += "### 🌐 Grafo Interativo\n\n"
        md += "Para uma exploração mais detalhada, uma versão interativa está disponível:\n\n"
        md += "[Clique aqui para visualizar o grafo interativo em HTML](collaboration_graph.html)\n\n"
        md += "---\n\n"

        # Seção Individual por Desenvolvedor
        md += "## 👤 Análise Individual de Desenvolvedores\n\n"
        
        for author in sorted(self.graph.nodes):
            successors = list(self.graph.successors(author))
            predecessors = list(self.graph.predecessors(author))
            connections_out = [(target, self.graph[author][target]['weight']) for target in successors]
            connections_in = [(source, self.graph[source][author]['weight']) for source in predecessors]

            if connections_out or connections_in:
                md += f"### {author}\n\n"
                
                # Resumo da posição na rede
                degree_centrality = nx.degree_centrality(self.graph)
                betweenness_centrality = nx.betweenness_centrality(self.graph)
                
                # Classificar o desenvolvedor em percentis
                degree_percentile = sum(1 for v in degree_centrality.values() if v <= degree_centrality[author]) / len(degree_centrality) * 100
                betweenness_percentile = sum(1 for v in betweenness_centrality.values() if v <= betweenness_centrality[author]) / len(betweenness_centrality) * 100
                
                md += "#### Perfil de Colaboração\n\n"
                md += f"- **Atribui issues para**: {len(successors)} desenvolvedores\n"
                md += f"- **Recebe issues de**: {len(predecessors)} desenvolvedores\n"
                md += f"- **Centralidade de grau**: {degree_centrality[author]:.4f} (percentil {degree_percentile:.0f}%)\n"
                md += f"- **Centralidade de intermediação**: {betweenness_centrality[author]:.4f} (percentil {betweenness_percentile:.0f}%)\n\n"
                
                # Classificação do papel
                role = ""
                if degree_percentile > 80 and betweenness_percentile > 80:
                    role = "Coordenador central (alta conexão e intermediação)"
                elif degree_percentile > 80:
                    role = "Hub de colaboração (muitas conexões diretas)"
                elif betweenness_percentile > 80:
                    role = "Ponte entre equipes (importante intermediário)"
                elif degree_percentile > 50 and betweenness_percentile > 50:
                    role = "Colaborador regular com papel de conexão"
                elif degree_percentile < 30 and betweenness_percentile < 30:
                    role = "Colaborador especializado com foco limitado"
                else:
                    role = "Colaborador com papel misto"
                
                md += f"**Papel na rede**: {role}\n\n"
                
                # Issues atribuídas a outros (saída)
                if connections_out:
                    md += "#### Issues Atribuídas a Outros\n\n"
                    md += "| Desenvolvedor | Total de Issues |\n"
                    md += "|---------------|----------------|\n"
                    for target, weight in sorted(connections_out, key=lambda x: x[1], reverse=True):
                        md += f"| {target} | {weight} |\n"
                    md += f"\n**Total de Issues Atribuídas**: {sum(w for _, w in connections_out)}\n\n"
                
                # Issues recebidas de outros (entrada)
                if connections_in:
                    md += "#### Issues Recebidas de Outros\n\n"
                    md += "| Desenvolvedor | Total de Issues |\n"
                    md += "|---------------|----------------|\n"
                    for source, weight in sorted(connections_in, key=lambda x: x[1], reverse=True):
                        md += f"| {source} | {weight} |\n"
                    md += f"\n**Total de Issues Recebidas**: {sum(w for _, w in connections_in)}\n\n"
                
                md += "---\n\n"

        return md

        print(f"📄 Relatório didático de colaboração gerado em: {output_path}")

    def plot_weighted(self, output_path="collaboration_graph_weighted.png"):
        plt.figure(figsize=(12, 10))
        pos = nx.spring_layout(self.graph, seed=42)

        # Calcular tamanhos dos nós baseados na centralidade de grau
        degree_centrality = nx.degree_centrality(self.graph)
        node_sizes = [5000 * degree_centrality[n] + 300 for n in self.graph.nodes]
        
        # Calcular cores dos nós baseadas na centralidade de intermediação
        betweenness_centrality = nx.betweenness_centrality(self.graph)
        node_colors = [betweenness_centrality[n] for n in self.graph.nodes]
        
        # Calcular larguras das arestas baseadas nos pesos
        edge_weights = [self.graph[u][v]['weight'] for u, v in self.graph.edges]

        # Desenhar nós
        nodes = nx.draw_networkx_nodes(
            self.graph, 
            pos, 
            node_color=node_colors, 
            node_size=node_sizes,
            cmap=plt.cm.viridis,
            alpha=0.8
        )
        
        # Desenhar labels
        nx.draw_networkx_labels(self.graph, pos, font_size=10, font_weight="bold")
        
        # Desenhar arestas com setas
        edges = nx.draw_networkx_edges(
            self.graph, 
            pos, 
            arrowstyle='->', 
            arrowsize=15,
            width=edge_weights, 
            edge_color='gray',
            alpha=0.6
        )

        # Adicionar colorbar para centralidade de intermediação
        plt.colorbar(nodes, label='Centralidade de Intermediação')

        plt.title("📌 Grafo de Colaboração (Tamanho: Centralidade de Grau, Cor: Centralidade de Intermediação)")
        plt.axis("off")
        plt.tight_layout()
        plt.savefig(output_path)
        plt.close()
        print(f"📊 Grafo ponderado salvo em: {output_path}")

    def plot_communities(self, output_path="collaboration_graph_communities.png"):
        """
        Visualiza as comunidades detectadas no grafo.
        """
        try:
            communities = self.detect_communities()
            partition = communities['partition']
            
            plt.figure(figsize=(12, 10))
            pos = nx.spring_layout(self.graph, seed=42)
            
            # Cores para cada comunidade
            num_communities = len(communities['communities'])
            cmap = plt.cm.get_cmap('tab20', max(num_communities, 2))  # Garantir pelo menos 2 cores
            
            # Desenhar nós coloridos por comunidade
            for idx, community in enumerate(communities['communities'].values()):
                nx.draw_networkx_nodes(
                    self.graph,
                    pos,
                    nodelist=community,
                    node_color=[cmap(idx % 20)] * len(community),  # Usar módulo 20 para evitar erros com muitas comunidades
                    node_size=300,
                    alpha=0.8,
                    label=f'Comunidade {idx+1}'
                )
            
            # Desenhar arestas
            nx.draw_networkx_edges(
                self.graph,
                pos,
                width=[self.graph[u][v].get('weight', 1) * 0.5 for u, v in self.graph.edges],
                alpha=0.5,
                edge_color='gray'
            )
            
            # Desenhar labels
            nx.draw_networkx_labels(self.graph, pos, font_size=10, font_weight="bold")
            
            plt.title("🌈 Comunidades de Desenvolvedores")
            plt.axis("off")
            plt.legend(scatterpoints=1, loc='lower left')
            plt.tight_layout()
            plt.savefig(output_path)
            plt.close()
            print(f"🎨 Grafo de comunidades salvo em: {output_path}")
        except Exception as e:
            print(f"⚠️ Não foi possível plotar comunidades: {e}")
            import traceback
            traceback.print_exc()

    def export_gexf(self, output_path="collaboration_graph.gexf"):
        nx.write_gexf(self.graph, output_path)
        print(f"🧠 Grafo exportado para Gephi: {output_path}")

    def generate_html_interactive(self, output_path="collaboration_graph.html"):
        pos = nx.spring_layout(self.graph, seed=42)
        
        # Calcular centralidades para uso no gráfico
        degree_centrality = nx.degree_centrality(self.graph)
        betweenness_centrality = nx.betweenness_centrality(self.graph)
        
        # Preparar dados para arestas
        edge_x = []
        edge_y = []
        edge_weights = []
        for u, v, weight in self.graph.edges(data='weight'):
            x0, y0 = pos[u]
            x1, y1 = pos[v]
            edge_x += [x0, x1, None]
            edge_y += [y0, y1, None]
            edge_weights.append(weight)

        # Preparar dados para nós
        node_x = []
        node_y = []
        node_text = []
        node_sizes = []
        node_colors = []
        for node in self.graph.nodes():
            x, y = pos[node]
            node_x.append(x)
            node_y.append(y)
            
            # Criar texto informativo para hover
            degree = degree_centrality[node]
            betweenness = betweenness_centrality[node]
            node_text.append(
                f"<b>{node}</b><br>" +
                f"Centralidade de Grau: {degree:.4f}<br>" +
                f"Centralidade de Intermediação: {betweenness:.4f}<br>" +
                f"Conexões: {self.graph.degree[node]}"
            )
            
            # Tamanho baseado na centralidade de grau
            node_sizes.append(degree * 50 + 10)
            
            # Cor baseada na centralidade de intermediação
            node_colors.append(betweenness)

        # Criar trace para arestas
        edge_trace = go.Scatter(
            x=edge_x, y=edge_y,
            line=dict(width=1, color='#888'),
            hoverinfo='none',
            mode='lines'
        )

        # Criar trace para nós
        node_trace = go.Scatter(
            x=node_x, y=node_y,
            mode='markers',
            hoverinfo='text',
            text=node_text,
            marker=dict(
                showscale=True,
                colorscale='Viridis',
                color=node_colors,
                size=node_sizes,
                colorbar=dict(
                    thickness=15,
                    title='Centralidade de Intermediação',
                    xanchor='left'
                ),
                line_width=2
            )
        )

        # Tentar adicionar informações de comunidade
        try:
            communities = self.detect_communities()
            partition = communities['partition']
            
            # Criar trace para comunidades
            community_colors = []
            community_sizes = []
            community_text = []
            
            for node in self.graph.nodes():
                community_id = partition.get(node, 0)  # Usar get com default para evitar KeyError
                community_colors.append(community_id)
                community_sizes.append(degree_centrality[node] * 50 + 10)
                community_text.append(
                    f"<b>{node}</b><br>" +
                    f"Comunidade: {community_id + 1}<br>" +
                    f"Centralidade de Grau: {degree_centrality[node]:.4f}<br>" +
                    f"Centralidade de Intermediação: {betweenness_centrality[node]:.4f}"
                )
            
            community_trace = go.Scatter(
                x=node_x, y=node_y,
                mode='markers',
                hoverinfo='text',
                text=community_text,
                marker=dict(
                    showscale=True,
                    colorscale='Rainbow',
                    color=community_colors,
                    size=community_sizes,
                    colorbar=dict(
                        thickness=15,
                        title='Comunidade',
                        xanchor='left',
                        titleside='right'
                    ),
                    line_width=2
                ),
                visible=False,
                name='Comunidades'
            )
            
            # Criar layout com botões para alternar entre visualizações
            fig = go.Figure(
                data=[edge_trace, node_trace, community_trace],
                layout=go.Layout(
                    title=dict(
                        text='📌 Grafo Interativo de Colaboração',
                        font=dict(size=16)
                    ),
                    showlegend=False,
                    hovermode='closest',
                    margin=dict(b=20, l=5, r=5, t=40),
                    updatemenus=[dict(
                        type="buttons",
                        buttons=[
                            dict(label="Centralidade de Intermediação",
                                 method="update",
                                 args=[{"visible": [True, True, False]}]),
                            dict(label="Comunidades",
                                 method="update",
                                 args=[{"visible": [True, False, True]}]),
                        ],
                        direction="right",
                        pad={"r": 10, "t": 10},
                        showactive=True,
                        x=0.1,
                        xanchor="left",
                        y=1.1,
                        yanchor="top"
                    )],
                    annotations=[dict(
                        text="Visualização:",
                        showarrow=False,
                        xref="paper", yref="paper",
                        x=0, y=1.085
                    )],
                    xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                    yaxis=dict(showgrid=False, zeroline=False, showticklabels=False)
                )
            )
        except Exception as e:
            # Se não conseguir detectar comunidades, criar figura simples
            fig = go.Figure(
                data=[edge_trace, node_trace],
                layout=go.Layout(
                    title=dict(
                        text='📌 Grafo Interativo de Colaboração',
                        font=dict(size=16)
                    ),
                    showlegend=False,
                    hovermode='closest',
                    margin=dict(b=20, l=5, r=5, t=40),
                    annotations=[dict(
                        text="Author → Assignee",
                        showarrow=False,
                        xref="paper", yref="paper",
                        x=0.005, y=-0.002
                    )],
                    xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                    yaxis=dict(showgrid=False, zeroline=False, showticklabels=False)
                )
            )

        plot(fig, filename=output_path, auto_open=False)
        print(f"🌐 Grafo interativo salvo em: {output_path}")

    def run(self):
        self.fetch_issues()
        self.build()
        
        # Analisar redes complexas
        print("🔍 Analisando redes complexas...")
        hubs = self.identify_hubs()
        print(f"🌟 Hubs identificados por grau: {', '.join([n for n, _ in hubs['degree'][:3]])}")
        
        distance = self.analyze_communication_distance()
        print(f"🔄 Distância média de comunicação: {distance['avg_shortest_path']:.2f} passos")
        
        small_world = self.analyze_small_world_effect()
        is_small_world = "Sim" if small_world['is_small_world'] else "Não"
        print(f"🌐 Efeito de mundo pequeno: {is_small_world} (σ = {small_world['sigma']:.2f})")
        
        # Gerar relatórios e visualizações
        md =  self.generate_markdown("collaboration_report.md")
        self.plot_weighted("collaboration_graph_weighted.png")
        self.plot_communities("collaboration_graph_communities.png")
        self.export_gexf("collaboration_graph.gexf")
        self.generate_html_interactive("collaboration_graph.html")
        self.save_func(self.report_dir,'collaboration_report.md', md)
