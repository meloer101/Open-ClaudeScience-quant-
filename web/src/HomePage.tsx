import { useState } from "react";
import "./HomePage.css";

type Lang = "en" | "zh";

const factorIdeas = [
  { name: "Earnings Quality Composite", ic: "0.072", color: "green" },
  { name: "Cross-Sectional Value Factor", ic: "0.085", color: "purple", active: true },
  { name: "Momentum Reversal (20D)", ic: "-0.018", color: "orange" },
  { name: "Accruals Anomaly", ic: "0.041", color: "green" },
  { name: "Volatility-Adjusted Growth", ic: "0.033", color: "green" },
];

const metricValues = ["18.7%", "1.34", "0.86", "-12.6%"];

const translations = {
  en: {
    nav: ["Product", "Workflow", "Library", "Docs"],
    openWorkbench: "Open workbench",
    hero: {
      eyebrow: "Local-first AI research workbench",
      h1a: "From idea to",
      h1em: "audited backtest.",
      body: "QuantBench turns a natural-language strategy idea into a reproducible, auditable research run — data, factor code, backtest, Reviewer checks, and a research note, all saved to a local artifact directory.",
      bullets: [
        "Coordinator Agent turns ideas into runnable factor code",
        "Reviewer engine flags lookahead bias, overfitting, and cost sensitivity",
        "Every run ships with metrics, charts, and a research note",
      ],
      primaryCta: "Open the workbench",
      secondaryCta: "See how it works",
      badge: "Local-first · macOS & Linux · Python 3.11+",
    },
    preview: {
      draft: "Draft",
      share: "Share",
      factorIdeas: "Factor Ideas",
      newIdea: "+ New idea",
      backtestSummary: "Backtest Summary",
      dateRange: "2010-01-01 – 2024-04-30",
      timeframes: "1Y   3Y   5Y   ",
      timeframeAll: "All",
      equityCurve: "Equity Curve",
      factorKey: "Factor (Long/Short)",
      marketKey: "Market (Neutral)",
      signalHeading: "Signal Explanation",
      signalBody:
        "High book-to-price stocks with improving profitability and low accruals have historically delivered superior risk-adjusted returns.",
      viewDetails: "View details →",
      noteHeading: "Research Note Preview",
      noteBody: "value_factor_research_note.md",
      openNote: "Open note →",
    },
    metricLabels: ["Annualized Return", "Sharpe Ratio", "Information Ratio", "Max Drawdown"],
    features: [
      {
        type: "network",
        title: "Discover & code factors",
        body: "Describe a hypothesis in natural language. The Coordinator Agent pulls data, writes compute(df) factor code, and iterates automatically.",
        link: "Explore factor discovery",
      },
      {
        type: "backtest",
        title: "Backtest with a Reviewer",
        body: "Vectorized single-name and cross-sectional backtests, reviewed for lookahead bias, overfitting (PBO/DSR), and cost or capacity sensitivity.",
        link: "Explore backtesting",
      },
      {
        type: "notes",
        title: "Reproducible artifacts",
        body: "Every run saves config, code, metrics, charts, and a research note to a local artifact directory — outputs are research only, never investment advice.",
        link: "Explore research notes",
      },
    ],
    artifacts: {
      kicker: "From idea to insight",
      heading: "Artifacts that hold up to review",
      body: "Every run produces reproducible artifacts: charts, code, metrics, and Reviewer findings you can audit.",
      chartHeading: "Performance vs. Market",
      chartBody: "Consistent outperformance across market cycles with controlled drawdowns.",
      codeHeading: "Reproducible Code",
      codeBody: "Transparent, versioned compute(df) code you can run and extend.",
      summaryHeading: "Research Summary",
      summaryTitle: "Cross-Sectional Value Factor",
      summaryBody: "The factor exhibits strong long-short performance with high information ratio and low turnover.",
    },
    cta: {
      heading: "Ready to run your first experiment?",
      body: "QuantBench runs locally on macOS and Linux, no cloud account required.",
      button: "Open the workbench",
    },
    footer: {
      tagline: "Local-first AI workbench for quant research.",
      columns: [
        { title: "Product", items: ["Overview", "Factor Discovery", "Backtesting", "Reviewer"] },
        { title: "Library", items: ["Experiment Library", "Factor Library", "Session Fork"] },
        { title: "Resources", items: ["Documentation", "Workflow Skills", "GitHub"] },
        { title: "Project", items: ["About", "Local Setup", "Safety"] },
      ],
      legal: "© 2026 QuantBench. Research only — not investment advice.",
    },
  },
  zh: {
    nav: ["产品", "工作流", "实验库", "文档"],
    openWorkbench: "打开工作台",
    hero: {
      eyebrow: "本地优先的 AI 研究工作台",
      h1a: "从一个想法，到",
      h1em: "经审查的回测。",
      body: "QuantBench 把一句自然语言策略想法，转换成可复现、可审计的研究实验——数据、因子代码、回测、Reviewer 检查与研究笔记，全部归档在本地 artifact 目录中。",
      bullets: [
        "Coordinator Agent 把想法转化为可运行的因子代码",
        "Reviewer 引擎自动检测未来函数、过拟合与成本敏感性",
        "每次运行都会产出指标、图表与研究笔记",
      ],
      primaryCta: "打开工作台",
      secondaryCta: "查看工作原理",
      badge: "本地优先 · macOS 与 Linux · Python 3.11+",
    },
    preview: {
      draft: "草稿",
      share: "分享",
      factorIdeas: "因子想法",
      newIdea: "+ 新想法",
      backtestSummary: "回测摘要",
      dateRange: "2010-01-01 – 2024-04-30",
      timeframes: "1年  3年  5年  ",
      timeframeAll: "全部",
      equityCurve: "净值曲线",
      factorKey: "因子（多空）",
      marketKey: "市场（中性）",
      signalHeading: "信号说明",
      signalBody: "高账面市值比、盈利能力改善且应计项目较低的股票，历史上呈现出更优的风险调整收益。",
      viewDetails: "查看详情 →",
      noteHeading: "研究笔记预览",
      noteBody: "value_factor_research_note.md",
      openNote: "打开笔记 →",
    },
    metricLabels: ["年化收益", "夏普比率", "信息比率", "最大回撤"],
    features: [
      {
        type: "network",
        title: "发现并编写因子",
        body: "用自然语言描述假设，Coordinator Agent 自动拉取数据、编写 compute(df) 因子代码并迭代。",
        link: "了解因子发现",
      },
      {
        type: "backtest",
        title: "由 Reviewer 审查的回测",
        body: "向量化单标的与截面回测，并由 Reviewer 自动检查未来函数、过拟合（PBO/DSR）、成本与容量敏感性。",
        link: "了解回测引擎",
      },
      {
        type: "notes",
        title: "可复现的研究产物",
        body: "每次运行都会把配置、代码、指标、图表和研究笔记归档到本地 artifact 目录——所有产物仅供研究参考，不构成投资建议。",
        link: "了解研究笔记",
      },
    ],
    artifacts: {
      kicker: "从想法到洞察",
      heading: "经得起审查的研究产物",
      body: "每次运行都会产出可复现的 artifact：图表、代码、指标，以及可供审计的 Reviewer 发现。",
      chartHeading: "对比市场的表现",
      chartBody: "在不同市场周期中保持稳定超额收益，同时控制回撤。",
      codeHeading: "可复现代码",
      codeBody: "透明、可版本化的 compute(df) 代码，可直接运行与扩展。",
      summaryHeading: "研究摘要",
      summaryTitle: "截面价值因子",
      summaryBody: "该因子展现出较强的多空表现、较高的信息比率与较低的换手率。",
    },
    cta: {
      heading: "准备好开始你的第一个研究实验了吗？",
      body: "QuantBench 在本地运行，支持 macOS 与 Linux，无需云端账号。",
      button: "打开工作台",
    },
    footer: {
      tagline: "面向量化研究者的本地优先 AI 工作台。",
      columns: [
        { title: "产品", items: ["概览", "因子发现", "回测引擎", "Reviewer"] },
        { title: "实验库", items: ["实验库", "因子库", "会话 Fork"] },
        { title: "资源", items: ["文档", "工作流 Skill", "GitHub"] },
        { title: "项目", items: ["关于", "本地部署", "安全须知"] },
      ],
      legal: "© 2026 QuantBench。仅供研究参考，不构成投资建议。",
    },
  },
} as const;

type PreviewCopy = (typeof translations)[keyof typeof translations]["preview"];

function BrandMark() {
  return (
    <span className="home-brand-mark" aria-hidden="true">
      <span />
    </span>
  );
}

function Sparkline({ color }: { color: string }) {
  return (
    <svg className={`sparkline sparkline-${color}`} viewBox="0 0 80 28" aria-hidden="true">
      <polyline points="2,21 12,18 21,20 30,14 39,16 48,10 57,13 68,7 78,4" />
    </svg>
  );
}

function EquityChart() {
  return (
    <svg className="equity-chart" viewBox="0 0 520 230" role="img" aria-label="Performance versus market line chart">
      {[30, 75, 120, 165, 210].map((y) => (
        <line key={y} x1="28" x2="500" y1={y} y2={y} />
      ))}
      {["2012", "2014", "2016", "2018", "2020", "2022", "2024"].map((year, index) => (
        <text key={year} x={58 + index * 68} y="216">
          {year}
        </text>
      ))}
      <polyline
        className="market-line"
        points="28,176 70,168 112,153 154,160 196,145 238,136 280,142 322,122 364,108 406,76 448,111 500,88"
      />
      <polyline
        className="factor-line"
        points="28,174 70,154 112,132 154,118 196,103 238,84 280,96 322,62 364,43 406,30 448,50 500,42"
      />
    </svg>
  );
}

function ProductPreview({
  spotlight,
  t,
  metricLabels,
}: {
  spotlight: boolean;
  t: PreviewCopy;
  metricLabels: readonly string[];
}) {
  return (
    <div className="product-preview" aria-label="Backtest workspace preview" data-spotlight={spotlight ? "true" : undefined}>
      <div className="preview-topbar">
        <div>
          <span className="preview-dot" /> Cross-Sectional Value Factor <span className="draft-pill">{t.draft}</span>
        </div>
        <div className="preview-actions">
          <button type="button">{t.share}</button>
          <button type="button" aria-label="More options">⋮</button>
        </div>
      </div>
      <div className="preview-body">
        <aside className="factor-list">
          <div className="panel-heading">
            <span>{t.factorIdeas}</span>
            <button type="button" aria-label="Add factor">+</button>
          </div>
          {factorIdeas.map((idea) => (
            <div className={`factor-item${idea.active ? " active" : ""}`} key={idea.name}>
              <div>
                <strong>{idea.name}</strong>
                <small>IC (1M) {idea.ic}</small>
              </div>
              <Sparkline color={idea.color} />
            </div>
          ))}
          <button className="new-idea-button" type="button">
            {t.newIdea}
          </button>
        </aside>
        <main className="backtest-panel">
          <div className="panel-heading stacked">
            <span>{t.backtestSummary}</span>
            <small>{t.dateRange}</small>
          </div>
          <div className="metric-grid">
            {metricLabels.map((label, index) => (
              <div className="metric-card" data-spotlight={spotlight ? "true" : undefined} key={label}>
                <small>{label}</small>
                <strong>{metricValues[index]}</strong>
              </div>
            ))}
          </div>
          <div className="chart-panel">
            <div className="chart-header">
              <strong>{t.equityCurve}</strong>
              <span>{t.timeframes}<b>{t.timeframeAll}</b></span>
            </div>
            <div className="legend">
              <span className="factor-key">{t.factorKey}</span>
              <span className="market-key">{t.marketKey}</span>
            </div>
            <EquityChart />
          </div>
          <div className="preview-cards">
            <div>
              <strong>{t.signalHeading}</strong>
              <p>{t.signalBody}</p>
              <a href="#details">{t.viewDetails}</a>
            </div>
            <div>
              <strong>{t.noteHeading}</strong>
              <p>{t.noteBody}</p>
              <a href="#research">{t.openNote}</a>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}

function FeatureIcon({ type }: { type: "network" | "backtest" | "notes" }) {
  return (
    <div className={`feature-icon feature-icon-${type}`} aria-hidden="true">
      {type === "network" && <span className="network-glyph" />}
      {type === "backtest" && <span className="backtest-glyph" />}
      {type === "notes" && <BrandMark />}
    </div>
  );
}

export function HomePage() {
  const [spotlightPreview, setSpotlightPreview] = useState(false);
  const [lang, setLang] = useState<Lang>("en");
  const t = translations[lang];

  return (
    <div className="home-page" lang={lang}>
      <header className="site-header">
        <a className="brand" href="/">
          <BrandMark />
          <span>QuantBench</span>
        </a>
        <nav aria-label="Main navigation">
          {t.nav.map((item) => (
            <a href={`#${item.toLowerCase()}`} key={item}>
              {item}
            </a>
          ))}
        </nav>
        <div className="header-actions">
          <button
            type="button"
            className="lang-toggle"
            onClick={() => setLang((current) => (current === "en" ? "zh" : "en"))}
            aria-label="Switch language"
          >
            {lang === "en" ? "中文" : "EN"}
          </button>
          <a className="button button-dark" href="/app">
            {t.openWorkbench}
          </a>
        </div>
      </header>

      <main>
        <section className="hero-section">
          <div className="hero-copy">
            <span className="eyebrow">{t.hero.eyebrow}</span>
            <h1>
              {t.hero.h1a}
              <br />
              {" "}
              <em>{t.hero.h1em}</em>
            </h1>
            <p>{t.hero.body}</p>
            <ul>
              {t.hero.bullets.map((bullet) => (
                <li key={bullet}>{bullet}</li>
              ))}
            </ul>
            <div className="hero-actions">
              <a className="button button-dark" href="/app">
                {t.hero.primaryCta}
              </a>
              <button
                className="button button-light"
                type="button"
                aria-pressed={spotlightPreview}
                onClick={() => setSpotlightPreview((current) => !current)}
              >
                <span aria-hidden="true">▷</span> {t.hero.secondaryCta}
              </button>
            </div>
            <div className="trusted">
              <span>{t.hero.badge}</span>
            </div>
          </div>
          <ProductPreview spotlight={spotlightPreview} t={t.preview} metricLabels={t.metricLabels} />
        </section>

        <section className="feature-grid" aria-label="Platform features">
          {t.features.map((feature) => (
            <article className="feature-card" key={feature.title}>
              <FeatureIcon type={feature.type as "network" | "backtest" | "notes"} />
              <h2>{feature.title}</h2>
              <p>{feature.body}</p>
              <a href="#product">{feature.link} →</a>
            </article>
          ))}
        </section>

        <section className="artifacts-section">
          <div className="section-intro">
            <div>
              <span className="section-kicker">{t.artifacts.kicker}</span>
              <h2>{t.artifacts.heading}</h2>
            </div>
            <p>{t.artifacts.body}</p>
          </div>
          <div className="artifact-grid">
            <article className="artifact-card chart-artifact">
              <h3>{t.artifacts.chartHeading}</h3>
              <EquityChart />
              <p>{t.artifacts.chartBody}</p>
            </article>
            <article className="artifact-card code-artifact">
              <div className="artifact-heading">
                <h3>{t.artifacts.codeHeading}</h3>
                <span>Python</span>
              </div>
              <pre>{`def compute(df):
    bp = df['book_equity'] / df['market_cap']
    roa = df['net_income'] / df['assets']
    accruals = df['total_accruals'] / df['assets']

    score = (
        0.5 * zscore(bp)
      + 0.3 * zscore(roa)
      - 0.2 * zscore(accruals)
    )
    return rank(score)`}</pre>
              <p>{t.artifacts.codeBody}</p>
            </article>
            <article className="artifact-card summary-artifact">
              <div className="artifact-heading">
                <h3>{t.artifacts.summaryHeading}</h3>
                <span>Markdown</span>
              </div>
              <h4>{t.artifacts.summaryTitle}</h4>
              <p>{t.artifacts.summaryBody}</p>
              <dl>
                {t.metricLabels.map((label, index) => (
                  <div key={label}>
                    <dt>{label}</dt>
                    <dd>{metricValues[index]}</dd>
                  </div>
                ))}
              </dl>
            </article>
          </div>
        </section>

        <section className="cta-band" id="access">
          <BrandMark />
          <div>
            <h2>{t.cta.heading}</h2>
            <p>{t.cta.body}</p>
          </div>
          <a className="button button-dark" href="/app">
            {t.cta.button}
          </a>
        </section>
      </main>

      <footer className="site-footer">
        <div>
          <a className="brand" href="/">
            <BrandMark />
            <span>QuantBench</span>
          </a>
          <p>{t.footer.tagline}</p>
        </div>
        {t.footer.columns.map((column) => (
          <div className="footer-column" key={column.title}>
            <strong>{column.title}</strong>
            {column.items.map((item) => (
              <a href={`#${item.toLowerCase().replaceAll(" ", "-")}`} key={item}>
                {item}
              </a>
            ))}
          </div>
        ))}
        <div className="footer-legal">
          <span>{t.footer.legal}</span>
        </div>
      </footer>
    </div>
  );
}
