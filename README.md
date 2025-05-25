# Reporfy — Turn GitHub data into powerful insights!

Reporfy is an advanced reporting tool that transforms GitHub project data into smart dashboards directly inside your repositories. All reports are generated in Markdown, making it lightweight, portable, and fully integrated into your GitHub workflows.

![reportfy](./reportfy_en.png)

✅ What Reporfy delivers:

* 📊 Productivity reports

* 🤝 Developer collaboration analysis

* 🔮 Delivery forecasts with Monte Carlo simulations

* 🔥 Flow metrics: burndown, burn-up, throughput

* 🌐 Network analysis applied to software engineering

✍️ Data generated in Markdown, allowing you to build dashboards inside your GitHub repositories

💡 Better decisions, powered by data. Simple, visual, and impactful management.

If you believe that “without data, it’s just an opinion”, then meet Reporfy!


## 🚀 Automation with GitHub Actions

Reporfy is fully automated using a **GitHub Action** that generates reports periodically or on demand. This allows your Markdown dashboards to be updated automatically inside your repository.

### ⚙️ How This Action Works

This GitHub Action is configured to:

- 🔁 **Run automatically at 8:00 AM (UTC) from Monday to Friday** (`cron: '0 8 * * 1-5'`).
- 🚀 **Run manually on demand** (uncomment the `workflow_dispatch` block if needed).

### 🔐 Required Secrets

You must configure the following **Secrets** in your repository:

| Secret        | Description                                                |
| --------------| ---------------------------------------------------------- |
| `TOKEN`       | GitHub Personal Access Token with read permissions for issues and commits. |
| `REPOSITORY`  | Full name of the repository (`owner/repository`).          |
