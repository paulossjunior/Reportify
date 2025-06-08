import os
import pandas as pd
import numpy as np
from dotenv import load_dotenv
import airbyte as ab
import matplotlib
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import random
from tqdm import tqdm

# Define fallback font with emoji support
matplotlib.rcParams['font.family'] = 'sans-serif'
matplotlib.rcParams['font.sans-serif'] = ['Noto Color Emoji', 'DejaVu Sans']


class GitHubIssueStats:
    def __init__(self,save_func,report_dir):
        load_dotenv()
        self.repository = os.getenv("GITHUB_REPOSITORY")
        self.token = os.getenv("GITHUB_TOKEN")
        self.issues_df = pd.DataFrame()
        self.monte_carlo_simulations = 1000  # Number of Monte Carlo simulations to run
        self.save_func = save_func
        self.report_dir = report_dir
    def fetch_issues(self):
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
        cache = ab.get_default_cache()
        source.read(cache=cache)
        self.issues_df = cache["issues"].to_pandas()

    def compute_stats(self) -> pd.DataFrame:
        grouped = self.issues_df.groupby(["repository", "state"]).size().reset_index(name="count")
        pivot = grouped.pivot(index="repository", columns="state", values="count").fillna(0).astype(int)
        for col in ["open", "closed"]:
            if col not in pivot.columns:
                pivot[col] = 0
        pivot["total"] = pivot["open"] + pivot["closed"]
        pivot["percent_closed"] = (pivot["closed"] / pivot["total"] * 100).round(1)
        return pivot.reset_index()

    def generate_markdown(self, stats_df: pd.DataFrame) -> str:
        markdown = "# 📈 Issue Stats by Repository and Status\n\n"
        markdown += "| Repository | 🟢 Open | 🔴 Closed | 📦 Total | ✅ % Closed |\n"
        markdown += "|------------|----------|------------|---------|------------|\n"
        for _, row in stats_df.iterrows():
            repo_name = row['repository']
            planning_icon = " 🗓️" if "planning" in repo_name.lower() else ""
            markdown += (
                f"| `{repo_name}`{planning_icon} | "
                f"{row['open']} | {row['closed']} | {row['total']} | {row['percent_closed']}% |\n"
            )
        return markdown

    def compute_weekly_delivery_stats(self) -> dict:
        df = self.issues_df.copy()
        df["created_at"] = pd.to_datetime(df["created_at"])
        df["week"] = df["created_at"].dt.to_period("W").apply(lambda r: r.start_time)
        grouped = df.groupby(["repository", "week", "state"]).size().unstack(fill_value=0)
        for col in ["open", "closed"]:
            if col not in grouped.columns:
                grouped[col] = 0
        grouped["promised"] = grouped["open"] + grouped["closed"]
        grouped["delivered"] = grouped["closed"]
        grouped["percent_completed"] = (grouped["closed"] / grouped["promised"]).fillna(0) * 100
        return {repo: df for repo, df in grouped.reset_index().groupby("repository")}

    def plot_weekly_delivery_per_repo(self, repo_weekly_data: dict, output_dir="charts_weekly"):
        os.makedirs(output_dir, exist_ok=True)
        for repo, df in repo_weekly_data.items():
            filename = repo.replace("/", "_") + "_weekly.png"
            weeks = df["week"].dt.strftime("%Y-%m-%d")
            promised = df["promised"]
            delivered = df["delivered"]
            percent_completed = df["percent_completed"].round(1)
            fig, ax1 = plt.subplots(figsize=(10, 4))
            bar_width = 0.4
            x = range(len(weeks))
            ax1.bar([i - bar_width / 2 for i in x], promised, width=bar_width, label="Prometido", color="navy")
            ax1.bar([i + bar_width / 2 for i in x], delivered, width=bar_width, label="Entregue", color="green")
            ax1.set_ylabel("Issues")
            ax1.set_xticks(x)
            ax1.set_xticklabels(weeks, rotation=45)
            ax1.legend(loc="upper left")
            ax2 = ax1.twinx()
            ax2.plot(x, percent_completed, color="darkred", marker="o", label="% Concluído")
            ax2.set_ylabel("% Concluído")
            ax2.set_ylim(0, 110)
            ax2.legend(loc="upper right")
            plt.title(f"{repo}\n📈 Entregas Semanais")
            plt.tight_layout()
            plt.savefig(os.path.join(output_dir, filename))
            plt.close()

    def plot_burnup_per_repo(self, repo_weekly_data: dict, output_dir="charts_burnup"):
        os.makedirs(output_dir, exist_ok=True)
        for repo, df in repo_weekly_data.items():
            filename = repo.replace("/", "_") + "_burnup.png"
            df = df.sort_values("week")
            df["cumulative_promised"] = df["promised"].cumsum()
            df["cumulative_delivered"] = df["delivered"].cumsum()
            
            # Convert weeks to list to ensure proper indexing
            weeks_list = df["week"].dt.strftime("%Y-%m-%d").tolist()
            x = range(len(weeks_list))
            
            plt.figure(figsize=(10, 4))
            plt.plot(x, df["cumulative_promised"], label="Prometido acumulado", color="blue", marker="o")
            plt.plot(x, df["cumulative_delivered"], label="Entregue acumulado", color="green", marker="o")
            plt.fill_between(x, df["cumulative_delivered"], df["cumulative_promised"], color="lightgray", alpha=0.3)
            
            if len(df) >= 2:
                z = pd.Series(df["cumulative_delivered"].values).interpolate(method='linear')
                trend = pd.Series(z).rolling(window=2, min_periods=1).mean()
                plt.plot(x, trend, linestyle="--", color="orange", label="Tendência")
                
                total_prometido = df["cumulative_promised"].max()
                if trend.iloc[-1] > 0 and len(trend) >= 2:
                    delta = trend.iloc[-1] - trend.iloc[-2]
                    if delta > 0:  # Only predict if there's positive progress
                        weeks_to_finish = (total_prometido - trend.iloc[-1]) / delta
                        if 0 < weeks_to_finish < 20:
                            # Calculate the future date directly instead of indexing
                            last_week_date = pd.to_datetime(df["week"].iloc[-1])
                            predicted_date = last_week_date + pd.Timedelta(days=int(weeks_to_finish * 7))
                            predicted_date_str = predicted_date.strftime('%Y-%m-%d')
                            # Add vertical line at prediction point
                            future_x = len(weeks_list) - 1 + weeks_to_finish
                            plt.axvline(x=future_x, linestyle=":", color="red", 
                                       label=f"Previsão: {predicted_date_str}")
            
            plt.xticks(x, weeks_list, rotation=45)
            plt.xlabel("Semana")
            plt.ylabel("Issues acumuladas")
            plt.title(f"{repo}\n🔥 Burn-up Chart")
            plt.legend()
            plt.tight_layout()
            plt.savefig(os.path.join(output_dir, filename))
            plt.close()

    def run_monte_carlo_simulation(self, repo_weekly_data: dict) -> dict:
        """Run Monte Carlo simulation to predict velocity and completion date for each repository."""
        results = {}
        
        for repo, df in repo_weekly_data.items():
            if len(df) < 2:  # Need at least 2 data points for a meaningful simulation
                results[repo] = {
                    'velocity_mean': 0,
                    'velocity_p10': 0,
                    'velocity_p50': 0,
                    'velocity_p90': 0,
                    'completion_date_p10': None,
                    'completion_date_p50': None,
                    'completion_date_p90': None,
                    'simulation_data': [],
                }
                continue
                
            # Sort data chronologically
            df = df.sort_values("week")
            
            # Extract historical velocities (delivery rates per week)
            velocities = df["delivered"].tolist()
            
            # Calculate remaining work
            df["cumulative_promised"] = df["promised"].cumsum()
            df["cumulative_delivered"] = df["delivered"].cumsum()
            remaining_work = df["cumulative_promised"].max() - df["cumulative_delivered"].max()
            
            if remaining_work <= 0:  # No work left to do
                results[repo] = {
                    'velocity_mean': np.mean(velocities),
                    'velocity_p10': np.percentile(velocities, 10) if len(velocities) > 0 else 0,
                    'velocity_p50': np.percentile(velocities, 50) if len(velocities) > 0 else 0,
                    'velocity_p90': np.percentile(velocities, 90) if len(velocities) > 0 else 0,
                    'completion_date_p10': "Complete",
                    'completion_date_p50': "Complete",
                    'completion_date_p90': "Complete",
                    'simulation_data': [],
                }
                continue
                
            # Get the last date in our dataset as our starting point
            last_date = pd.to_datetime(df["week"].max())
            
            # Run simulations
            simulation_data = []
            for _ in range(self.monte_carlo_simulations):
                # For each simulation, randomly sample from historical velocities
                # with bootstrap resampling (sampling with replacement)
                sampled_velocities = random.choices(velocities, k=len(velocities))
                
                # Calculate mean velocity from our sampled data
                # Add a small random factor (±20%) to represent uncertainty
                mean_velocity = np.mean(sampled_velocities) * random.uniform(0.8, 1.2)
                
                # Skip if velocity is zero or negative
                if mean_velocity <= 0:
                    continue
                
                # Calculate weeks to completion based on sampled velocity
                weeks_to_completion = remaining_work / mean_velocity
                
                # Calculate completion date
                completion_date = last_date + pd.Timedelta(days=int(weeks_to_completion * 7))
                
                # Store results for this simulation
                simulation_data.append({
                    'velocity': mean_velocity,
                    'weeks_to_completion': weeks_to_completion,
                    'completion_date': completion_date
                })
            
            # If we have simulation data, calculate statistics
            if simulation_data:
                # Extract velocities and completion dates from all simulations
                all_velocities = [sim['velocity'] for sim in simulation_data]
                all_completion_dates = [sim['completion_date'] for sim in simulation_data]
                
                # Calculate percentiles for velocity
                velocity_mean = np.mean(all_velocities)
                velocity_p10 = np.percentile(all_velocities, 10)
                velocity_p50 = np.percentile(all_velocities, 50)
                velocity_p90 = np.percentile(all_velocities, 90)
                
                # Calculate percentiles for completion date
                completion_dates_sorted = sorted(all_completion_dates)
                idx_p10 = min(int(0.1 * len(completion_dates_sorted)), len(completion_dates_sorted) - 1)
                idx_p50 = min(int(0.5 * len(completion_dates_sorted)), len(completion_dates_sorted) - 1)
                idx_p90 = min(int(0.9 * len(completion_dates_sorted)), len(completion_dates_sorted) - 1)
                
                completion_date_p10 = completion_dates_sorted[idx_p10]
                completion_date_p50 = completion_dates_sorted[idx_p50]
                completion_date_p90 = completion_dates_sorted[idx_p90]
                
                results[repo] = {
                    'velocity_mean': velocity_mean,
                    'velocity_p10': velocity_p10,
                    'velocity_p50': velocity_p50,
                    'velocity_p90': velocity_p90,
                    'completion_date_p10': completion_date_p10.strftime('%Y-%m-%d'),
                    'completion_date_p50': completion_date_p50.strftime('%Y-%m-%d'),
                    'completion_date_p90': completion_date_p90.strftime('%Y-%m-%d'),
                    'simulation_data': simulation_data,
                }
            else:
                # No valid simulations, provide default results
                results[repo] = {
                    'velocity_mean': np.mean(velocities) if velocities else 0,
                    'velocity_p10': 0,
                    'velocity_p50': 0,
                    'velocity_p90': 0,
                    'completion_date_p10': None,
                    'completion_date_p50': None,
                    'completion_date_p90': None,
                    'simulation_data': [],
                }
                
        return results

    def plot_monte_carlo_simulations(self, repo_weekly_data: dict, monte_carlo_results: dict, output_dir="charts_monte_carlo"):
        """Create Monte Carlo simulation visualizations for each repository."""
        os.makedirs(output_dir, exist_ok=True)
        
        for repo, mc_data in monte_carlo_results.items():
            if not mc_data['simulation_data']:
                continue  # Skip if no simulation data
                
            # Histogram of completion dates
            filename = repo.replace("/", "_") + "_monte_carlo.png"
            plt.figure(figsize=(10, 6))
            
            # Extract completion dates
            completion_dates = [sim['completion_date'] for sim in mc_data['simulation_data']]
            
            # Calculate bins - one for each week
            min_date = min(completion_dates)
            max_date = max(completion_dates)
            weeks_span = (max_date - min_date).days // 7 + 1
            bins = min(weeks_span, 20)  # Limit to 20 bins max
            
            # Convert dates to numerical format for histogram
            completion_dates_num = [(date - min_date).days / 7 for date in completion_dates]
            
            # Plot histogram
            plt.hist(completion_dates_num, bins=bins, alpha=0.7, color='blue')
            
            # Add percentile lines
            p10_idx = int(len(completion_dates) * 0.1)
            p50_idx = int(len(completion_dates) * 0.5)
            p90_idx = int(len(completion_dates) * 0.9)
            
            sorted_dates_num = sorted(completion_dates_num)
            p10_value = sorted_dates_num[p10_idx] if p10_idx < len(sorted_dates_num) else sorted_dates_num[-1]
            p50_value = sorted_dates_num[p50_idx] if p50_idx < len(sorted_dates_num) else sorted_dates_num[-1]
            p90_value = sorted_dates_num[p90_idx] if p90_idx < len(sorted_dates_num) else sorted_dates_num[-1]
            
            plt.axvline(x=p10_value, color='green', linestyle='--', label='P10 (Otimista)')
            plt.axvline(x=p50_value, color='orange', linestyle='--', label='P50 (Provável)')
            plt.axvline(x=p90_value, color='red', linestyle='--', label='P90 (Conservador)')
            
            # Set x-axis ticks to show dates
            tick_positions = np.linspace(0, max(completion_dates_num), min(10, bins))
            tick_labels = [(min_date + pd.Timedelta(days=int(pos * 7))).strftime('%Y-%m-%d') for pos in tick_positions]
            plt.xticks(tick_positions, tick_labels, rotation=45)
            
            plt.title(f"{repo}\n🎲 Simulação Monte Carlo - Previsão de Conclusão")
            plt.xlabel("Data de Conclusão Prevista")
            plt.ylabel("Número de Simulações")
            plt.legend()
            plt.tight_layout()
            plt.savefig(os.path.join(output_dir, filename))
            plt.close()
            
            # Create velocity distribution chart
            vel_filename = repo.replace("/", "_") + "_velocity_dist.png"
            plt.figure(figsize=(10, 4))
            
            velocities = [sim['velocity'] for sim in mc_data['simulation_data']]
            plt.hist(velocities, bins=min(20, len(velocities)//5 + 1), alpha=0.7, color='green')
            
            plt.axvline(x=mc_data['velocity_p10'], color='green', linestyle='--', label='P10')
            plt.axvline(x=mc_data['velocity_p50'], color='orange', linestyle='--', label='P50')
            plt.axvline(x=mc_data['velocity_p90'], color='red', linestyle='--', label='P90')
            
            plt.title(f"{repo}\n📊 Distribuição de Velocidade")
            plt.xlabel("Velocidade (issues/semana)")
            plt.ylabel("Frequência")
            plt.legend()
            plt.tight_layout()
            plt.savefig(os.path.join(output_dir, vel_filename))
            plt.close()

    def append_monte_carlo_results_to_markdown(self, monte_carlo_results: dict, output_dir="charts_monte_carlo") -> str:
        """Add Monte Carlo simulation results to the markdown report."""
        markdown = "\n---\n# 🎲 Simulação Monte Carlo\n\n"
        markdown += "A simulação Monte Carlo usa dados históricos de velocidade para prever datas de conclusão com diferentes níveis de confiança:\n\n"
        markdown += "- **P10 (Otimista)**: 10% de chance de concluir antes desta data (melhor cenário)\n"
        markdown += "- **P50 (Provável)**: 50% de chance de concluir antes desta data (cenário mais provável)\n"
        markdown += "- **P90 (Conservador)**: 90% de chance de concluir antes desta data (pior cenário)\n\n"
        
        markdown += "## Resultados da Simulação por Repositório\n\n"
        
        for repo, results in monte_carlo_results.items():
            safe_repo = repo.replace("/", "_")
            markdown += f"### `{repo}`\n\n"
            
            # Add Monte Carlo charts if available
            if results['simulation_data']:
                mc_file = f"{output_dir}/{safe_repo}_monte_carlo.png"
                vel_file = f"{output_dir}/{safe_repo}_velocity_dist.png"
                markdown += f"![{repo} monte carlo simulation]({mc_file})\n\n"
                markdown += f"![{repo} velocity distribution]({vel_file})\n\n"
            
            # Create a table with the results
            markdown += "#### Previsões de Velocidade e Conclusão\n\n"
            markdown += "| Métrica | Valor |\n"
            markdown += "|--------|-------|\n"
            
            markdown += f"| Velocidade Média | {results['velocity_mean']:.2f} issues/semana |\n"
            markdown += f"| Velocidade P10 (Otimista) | {results['velocity_p10']:.2f} issues/semana |\n"
            markdown += f"| Velocidade P50 (Provável) | {results['velocity_p50']:.2f} issues/semana |\n"
            markdown += f"| Velocidade P90 (Conservador) | {results['velocity_p90']:.2f} issues/semana |\n"
            
            if results['completion_date_p10'] == "Complete":
                markdown += f"| Conclusão | Já concluído |\n"
            elif results['completion_date_p10'] is None:
                markdown += f"| Conclusão | Dados insuficientes para previsão |\n"
            else:
                markdown += f"| Data de Conclusão P10 (Otimista) | {results['completion_date_p10']} |\n"
                markdown += f"| Data de Conclusão P50 (Provável) | {results['completion_date_p50']} |\n"
                markdown += f"| Data de Conclusão P90 (Conservador) | {results['completion_date_p90']} |\n"
            
            markdown += "\n"
            
            # Add detailed Monte Carlo explanation table
            markdown += "#### Explicação da Simulação Monte Carlo\n\n"
            markdown += "| Conceito | Explicação |\n"
            markdown += "|---------|------------|\n"
            markdown += "| **O que é Monte Carlo?** | Técnica estatística que utiliza amostragens aleatórias repetidas para obter resultados numéricos e estimar probabilidades. |\n"
            markdown += "| **Como funciona a simulação?** | 1) Coletamos o histórico de velocidade do time (issues concluídas/semana)<br>2) Fazemos 1000 simulações com variações aleatórias dessas velocidades<br>3) Para cada simulação, calculamos quando o trabalho restante seria concluído<br>4) Organizamos os resultados e calculamos os percentis |\n"
            markdown += "| **O que significa P10?** | Cenário otimista. Existe apenas 10% de chance de concluir o trabalho antes desta data. É um resultado rápido e favorável, mas menos provável. |\n"
            markdown += "| **O que significa P50?** | Cenário mais provável. 50% de chance de terminar antes ou depois desta data. É nossa melhor estimativa 'realista'. |\n"
            markdown += "| **O que significa P90?** | Cenário conservador. Existe 90% de chance de concluir antes desta data. Útil para planejamento seguro, pois é improvável atrasar além deste ponto. |\n"
            markdown += "| **Por que usar Monte Carlo?** | Fornece intervalos de confiança em vez de datas únicas, reconhecendo a incerteza natural no desenvolvimento. Captura a variabilidade histórica do time. |\n"
            markdown += "| **Como interpretar velocidades?** | Quanto maior a velocidade, mais rápido o time conclui issues. P10/P50/P90 para velocidades mostram diferentes cenários de produtividade que usamos nos cálculos. |\n"
            
            # Add historical data context if simulation data exists
            if results['simulation_data'] and len(results['simulation_data']) > 0:
                historical_context = "| **Contexto dos dados** | "
                
                # Calculate remaining work and time to completion
                if results['completion_date_p10'] != "Complete" and results['completion_date_p10'] is not None:
                    # Extract velocity info
                    historical_velocities = []
                    for sim in results['simulation_data']:
                        if 'velocity' in sim:
                            historical_velocities.append(sim['velocity'])
                    
                    # Calculate volatility (coefficient of variation)
                    if historical_velocities:
                        mean_velocity = np.mean(historical_velocities)
                        std_velocity = np.std(historical_velocities)
                        volatility = (std_velocity / mean_velocity) * 100 if mean_velocity > 0 else 0
                        
                        # Interpret volatility
                        if volatility < 20:
                            volatility_desc = "baixa volatilidade (equipe consistente)"
                        elif volatility < 40:
                            volatility_desc = "volatilidade moderada (alguma variação na entrega)"
                        else:
                            volatility_desc = "alta volatilidade (entregas inconsistentes)"
                        
                        # Calculate spread between optimistic and conservative
                        if results['completion_date_p10'] and results['completion_date_p90']:
                            p10_date = pd.to_datetime(results['completion_date_p10'])
                            p90_date = pd.to_datetime(results['completion_date_p90'])
                            delta_days = (p90_date - p10_date).days
                            
                            historical_context += f"Com base nos dados históricos, a equipe tem {volatility_desc}. "
                            historical_context += f"A diferença entre o cenário otimista e conservador é de {delta_days} dias. "
                            
                            # Add recommendation based on data quality
                            if volatility < 30:
                                historical_context += f"Os dados são confiáveis para planejamento. Recomendamos usar P50 ({results['completion_date_p50']}) para comunicação de prazos."
                            else:
                                historical_context += f"Devido à alta variabilidade, considere usar P70-P80 para comunicação de prazos ao invés de P50."
                
                historical_context += " |"
                markdown += historical_context + "\n"
            
            markdown += "\n\n"
        
        return markdown

    def append_weekly_charts_to_markdown(self, repo_weekly_data: dict, monte_carlo_results: dict, output_dir="charts_weekly") -> str:
        markdown = "\n---\n# Gráficos e Previsões por Repositório\n\n"
        
        for repo, df in repo_weekly_data.items():
            safe_repo = repo.replace("/", "_")
            weekly_file = f"{output_dir}/{safe_repo}_weekly.png"
            burnup_file = f"charts_burnup/{safe_repo}_burnup.png"
            markdown += f"## `{repo}`\n\n"
            
            # Weekly Charts Section
            markdown += "### 📊 Entregas Semanais\n\n"
            markdown += f"![{repo} weekly chart]({weekly_file})\n\n"

            # Calcular velocidade semanal (entregues)
            df = df.sort_values("week")
            df["velocity"] = df["delivered"]

            # Velocidade média
            avg_velocity = df["velocity"].mean().round(2)
            markdown += f"**Velocidade média semanal:** {avg_velocity} issues/semana\n\n"

            # Tabela explicativa abaixo do gráfico
            markdown += "| Semana | Prometido | Entregue | % Concluído | Velocidade |\n"
            markdown += "|--------|------------|----------|--------------|------------|\n"
            for _, row in df.iterrows():
                week = row['week'].strftime('%Y-%m-%d')
                markdown += f"| {week} | {int(row['promised'])} | {int(row['delivered'])} | {round(row['percent_completed'], 1)}% | {int(row['velocity'])} |\n"
            markdown += "\n"

            # Burn-up chart
            markdown += f"### 🔥 Burn-up Chart\n\n"
            markdown += f"![{repo} burnup chart]({burnup_file})\n\n"

            # Previsão de término (método linear)
            df["cumulative_promised"] = df["promised"].cumsum()
            df["cumulative_delivered"] = df["delivered"].cumsum()
            
            # Only attempt prediction if we have enough data points
            if len(df) >= 2:
                trend_values = df["cumulative_delivered"].values
                trend = pd.Series(trend_values).interpolate(method='linear')
                trend = trend.rolling(window=2, min_periods=1).mean()
                total_prometido = df["cumulative_promised"].max()
                predicted_line = ""
                
                if len(trend) >= 2 and trend.iloc[-1] > 0:
                    delta = trend.iloc[-1] - trend.iloc[-2]
                    if delta > 0:  # Only predict if there's positive progress
                        weeks_to_finish = (total_prometido - trend.iloc[-1]) / delta
                        if 0 < weeks_to_finish < 20:
                            # Calculate the future date directly
                            last_week_date = pd.to_datetime(df["week"].iloc[-1])
                            predicted_date = last_week_date + pd.Timedelta(days=int(weeks_to_finish * 7))
                            predicted_date_str = predicted_date.strftime('%Y-%m-%d')
                            predicted_line = f"**Previsão de conclusão (linear):** {predicted_date_str}\n\n"

                if predicted_line:
                    markdown += predicted_line + "\n"
            
            # Add Monte Carlo section for this repo if results exist
            if repo in monte_carlo_results:
                results = monte_carlo_results[repo]
                markdown += f"### 🎲 Simulação Monte Carlo\n\n"
                
                # Add Monte Carlo charts if available
                if results['simulation_data']:
                    mc_file = f"charts_monte_carlo/{safe_repo}_monte_carlo.png"
                    vel_file = f"charts_monte_carlo/{safe_repo}_velocity_dist.png"
                    markdown += f"![{repo} monte carlo simulation]({mc_file})\n\n"
                    markdown += f"![{repo} velocity distribution]({vel_file})\n\n"
                
                # Create a table with the results
                markdown += "#### Previsões de Velocidade e Conclusão\n\n"
                markdown += "| Métrica | Valor |\n"
                markdown += "|--------|-------|\n"
                
                markdown += f"| Velocidade Média | {results['velocity_mean']:.2f} issues/semana |\n"
                markdown += f"| Velocidade P10 (Otimista) | {results['velocity_p10']:.2f} issues/semana |\n"
                markdown += f"| Velocidade P50 (Provável) | {results['velocity_p50']:.2f} issues/semana |\n"
                markdown += f"| Velocidade P90 (Conservador) | {results['velocity_p90']:.2f} issues/semana |\n"
                
                if results['completion_date_p10'] == "Complete":
                    markdown += f"| Conclusão | Já concluído |\n"
                elif results['completion_date_p10'] is None:
                    markdown += f"| Conclusão | Dados insuficientes para previsão |\n"
                else:
                    markdown += f"| Data de Conclusão P10 (Otimista) | {results['completion_date_p10']} |\n"
                    markdown += f"| Data de Conclusão P50 (Provável) | {results['completion_date_p50']} |\n"
                    markdown += f"| Data de Conclusão P90 (Conservador) | {results['completion_date_p90']} |\n"
                
                markdown += "\n"
                
                # Add detailed Monte Carlo explanation table
                markdown += "#### Explicação da Simulação Monte Carlo\n\n"
                markdown += "| Conceito | Explicação |\n"
                markdown += "|---------|------------|\n"
                markdown += "| **O que é Monte Carlo?** | Técnica estatística que utiliza amostragens aleatórias repetidas para obter resultados numéricos e estimar probabilidades. |\n"
                markdown += "| **Como funciona a simulação?** | 1) Coletamos o histórico de velocidade do time (issues concluídas/semana)<br>2) Fazemos 1000 simulações com variações aleatórias dessas velocidades<br>3) Para cada simulação, calculamos quando o trabalho restante seria concluído<br>4) Organizamos os resultados e calculamos os percentis |\n"
                markdown += "| **O que significa P10?** | Cenário otimista. Existe apenas 10% de chance de concluir o trabalho antes desta data. É um resultado rápido e favorável, mas menos provável. |\n"
                markdown += "| **O que significa P50?** | Cenário mais provável. 50% de chance de terminar antes ou depois desta data. É nossa melhor estimativa 'realista'. |\n"
                markdown += "| **O que significa P90?** | Cenário conservador. Existe 90% de chance de concluir antes desta data. Útil para planejamento seguro, pois é improvável atrasar além deste ponto. |\n"
                markdown += "| **Por que usar Monte Carlo?** | Fornece intervalos de confiança em vez de datas únicas, reconhecendo a incerteza natural no desenvolvimento. Captura a variabilidade histórica do time. |\n"
                markdown += "| **Como interpretar velocidades?** | Quanto maior a velocidade, mais rápido o time conclui issues. P10/P50/P90 para velocidades mostram diferentes cenários de produtividade que usamos nos cálculos. |\n"
                
                # Add historical data context if simulation data exists
                if results['simulation_data'] and len(results['simulation_data']) > 0:
                    historical_context = "| **Contexto dos dados** | "
                    
                    # Calculate remaining work and time to completion
                    if results['completion_date_p10'] != "Complete" and results['completion_date_p10'] is not None:
                        # Extract velocity info
                        historical_velocities = []
                        for sim in results['simulation_data']:
                            if 'velocity' in sim:
                                historical_velocities.append(sim['velocity'])
                        
                        # Calculate volatility (coefficient of variation)
                        if historical_velocities:
                            mean_velocity = np.mean(historical_velocities)
                            std_velocity = np.std(historical_velocities)
                            volatility = (std_velocity / mean_velocity) * 100 if mean_velocity > 0 else 0
                            
                            # Interpret volatility
                            if volatility < 20:
                                volatility_desc = "baixa volatilidade (equipe consistente)"
                            elif volatility < 40:
                                volatility_desc = "volatilidade moderada (alguma variação na entrega)"
                            else:
                                volatility_desc = "alta volatilidade (entregas inconsistentes)"
                            
                            # Calculate spread between optimistic and conservative
                            if results['completion_date_p10'] and results['completion_date_p90']:
                                p10_date = pd.to_datetime(results['completion_date_p10'])
                                p90_date = pd.to_datetime(results['completion_date_p90'])
                                delta_days = (p90_date - p10_date).days
                                
                                historical_context += f"Com base nos dados históricos, a equipe tem {volatility_desc}. "
                                historical_context += f"A diferença entre o cenário otimista e conservador é de {delta_days} dias. "
                                
                                # Add recommendation based on data quality
                                if volatility < 30:
                                    historical_context += f"Os dados são confiáveis para planejamento. Recomendamos usar P50 ({results['completion_date_p50']}) para comunicação de prazos."
                                else:
                                    historical_context += f"Devido à alta variabilidade, considere usar P70-P80 para comunicação de prazos ao invés de P50."
                    
                    historical_context += " |"
                    markdown += historical_context + "\n"
            
            # Add separator between repositories
            markdown += "\n---\n\n"

        return markdown

    def run(self):
        print("🔄 Buscando issues...")
        self.fetch_issues()
        print("✅ Issues carregadas.")
        
        stats_df = self.compute_stats()
        print("📊 Estatísticas principais computadas.")
        
        markdown = self.generate_markdown(stats_df)
        
        repo_weekly_data = self.compute_weekly_delivery_stats()
        
        print("🎲 Executando simulações Monte Carlo...")
        monte_carlo_results = self.run_monte_carlo_simulation(repo_weekly_data)
        print("✅ Simulações Monte Carlo concluídas.")
        
        self.plot_weekly_delivery_per_repo(repo_weekly_data)
        self.plot_burnup_per_repo(repo_weekly_data)
        self.plot_monte_carlo_simulations(repo_weekly_data, monte_carlo_results)
        
        # Passando o monte_carlo_results para o método append_weekly_charts_to_markdown
        markdown += self.append_weekly_charts_to_markdown(repo_weekly_data, monte_carlo_results)
        
        self.save_func(self.report_dir, "repository_stats.md", markdown)
        print("✅ Markdown e gráficos salvos com sucesso!")
  