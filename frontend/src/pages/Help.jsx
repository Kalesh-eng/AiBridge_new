/**
 * Help.jsx — AIBridge help documentation page
 * Searchable docs covering all features, like software help manual
 */

import { useState } from 'react'
import { PageHeader, PageBody } from '../components/Layout'

const DOCS = [
  {
    section: 'Getting Started',
    icon: '🚀',
    articles: [
      {
        title: 'What is AIBridge?',
        content: `AIBridge is an AI-powered ETL (Extract, Transform, Load) platform that turns plain English into fully automated data pipelines. Instead of writing complex SQL or configuring ETL tools manually, you simply describe your data and analytics goals — AIBridge handles everything else.

Key capabilities:
• Connect to any database (PostgreSQL, MySQL, SQL Server, Oracle, Snowflake, BigQuery, and more)
• Upload CSV or Excel files directly
• AI generates star schema, SQL scripts, and ETL mappings automatically
• Built-in data quality checks before loading
• Natural language BI queries — ask questions, get charts instantly
• Supports on-premises deployment for air-gapped environments (banks, regulated industries)`
      },
      {
        title: 'Quick start guide',
        content: `Get your first pipeline running in 5 minutes:

Step 1 — Add a connector
Go to Connectors → click "Add connector". Enter your database credentials and click "Test connection". Save when successful.

Step 2 — Upload a file (optional)
If you have a CSV or Excel file, drag and drop it on the Connectors page. AIBridge creates a DuckDB connector automatically.

Step 3 — Run the ETL Agent
Go to ETL Agent → select your connector → describe your data in plain English → click "Design pipeline". Review the proposed star schema and approve it.

Step 4 — Execute
Go to Pipelines → find your pipeline → click Execute. Watch live logs as data flows from source → staging → warehouse.

Step 5 — Analyse
Go to BI / Analytics → ask questions about your data in plain English → get SQL and charts instantly.`
      },
      {
        title: 'Supported databases',
        content: `AIBridge supports all major databases as both source and target:

On-premises:
• PostgreSQL (recommended for warehouse target)
• MySQL / MariaDB
• SQL Server
• Oracle
• SQLite

Cloud:
• Snowflake
• Google BigQuery
• Amazon Redshift
• Azure SQL

File sources:
• CSV files (auto-loaded into DuckDB)
• Excel (.xlsx) files

Air-gapped / on-premises deployment:
AIBridge supports running LLMs locally via Ollama, making it suitable for banks and regulated industries where data cannot leave the premises. Contact your administrator to configure the AI provider.`
      },
    ]
  },
  {
    section: 'Connectors',
    icon: '🔌',
    articles: [
      {
        title: 'Adding a database connector',
        content: `To connect a database:

1. Go to Connectors in the left navigation
2. Click "Add connector"
3. Select your database type (PostgreSQL, MySQL, etc.)
4. Enter connection details:
   • Name — a friendly label for this connection
   • Host — database server hostname or IP
   • Port — default ports: PostgreSQL=5432, MySQL=3306, SQL Server=1433
   • Database name — the specific database to connect to
   • Username and password
5. Click "Test connection" to verify credentials
6. Click "Save" to store the connector

Tip: For the warehouse target (where your star schema will be built), use a PostgreSQL database. This is the most reliable target for AIBridge's generated SQL.`
      },
      {
        title: 'Uploading CSV or Excel files',
        content: `AIBridge supports flat file sources directly:

1. Go to Connectors
2. Drag and drop your CSV or Excel file onto the upload area, or click "Upload file"
3. AIBridge loads your file into DuckDB automatically
4. A connector is created with the file's table name
5. You can now use this as a source in the ETL Agent

Re-uploading: If your data changes, click the "🔄 Re-upload file" button on an existing DuckDB connector to replace the data without losing your pipeline configuration.

Supported formats: .csv, .xlsx (Excel 2007+)`
      },
      {
        title: 'Connector roles',
        content: `Each connector has a role that determines how AIBridge uses it:

Source — reads raw data from this database
Target — writes warehouse tables (dim_*, fact_*) to this database
Both — used as both source and target (common for single-database setups)

For DuckDB file connectors, the role is always "source" — AIBridge automatically finds a PostgreSQL connector to use as the warehouse target.`
      },
    ]
  },
  {
    section: 'ETL Agent',
    icon: '⚙️',
    articles: [
      {
        title: 'How the ETL Agent works',
        content: `The ETL Agent is AIBridge's core AI pipeline designer. It runs in two phases:

Phase 1 — Data model design:
• SchemaAgent discovers your tables and columns
• BusinessAgent analyses your analytics requirements
• DataModelAgent designs a star schema (fact tables + dimension tables)
• You review and approve the proposed design (Human-in-the-Loop Gate 1)

Phase 2 — SQL generation:
• SQLAgent generates CREATE TABLE and INSERT SQL for each table
• SQLValidationAgent checks and auto-fixes common errors
• GovernanceAgent checks for PII and safety issues
• You review the SQL scripts (Human-in-the-Loop Gate 2)

After both approvals, save the pipeline and execute it.`
      },
      {
        title: 'Writing good business requirements',
        content: `The quality of your pipeline depends heavily on how you describe your data. Here are tips for writing effective requirements:

Good examples:
• "Used car sales data with 20 columns. I need to analyse average selling price by brand, model, year, and fuel type. Show price trends by year and compare manual vs automatic transmission prices."
• "Banking transaction data with customer accounts and branches. I need monthly transaction volumes, customer segment analysis, and branch performance KPIs."

Tips:
• Mention the domain (retail, banking, healthcare, etc.)
• List the key metrics you want to analyse (average price, total sales, count)
• Mention the dimensions you want to group by (brand, region, date, category)
• Keep it concise — 2-4 sentences is ideal

Avoid:
• Very vague descriptions ("analyse my data")
• Technical jargon that isn't business-relevant
• Describing how to build it (let AI decide the approach)`
      },
      {
        title: 'Human-in-the-Loop (HIL) approval gates',
        content: `AIBridge uses two approval gates to keep you in control:

Gate 1 — Data model approval:
After the ETL Agent designs the star schema, you review:
• Fact tables and their measures
• Dimension tables and their attributes  
• The overall data model structure

You can edit the model before approving. Once approved, the agent generates SQL.

Gate 2 — SQL approval:
You review the generated SQL scripts before they run. This lets you:
• Check for correctness
• Modify scripts if needed
• Spot any issues before data is loaded

HIL modes (set in workspace settings):
• Strict — always require human approval (default)
• Balanced — approve only high-risk changes
• Full auto — skip approvals (not recommended for production)`
      },
    ]
  },
  {
    section: 'Pipelines',
    icon: '📋',
    articles: [
      {
        title: 'Executing a pipeline',
        content: `To run a pipeline:

1. Go to Pipelines
2. Find your pipeline in the list
3. Click the "▶ Execute" button
4. Watch live logs stream in real time
5. Use the "⏹ Stop" button to cancel if needed

What happens during execution:
• Extract: data is copied from source to staging schema
• Quality check: AI scans staging for nulls, duplicates, business rule violations
• Bad rows are quarantined to warehouse.dq_audit_log
• Load: warehouse scripts run to build dim and fact tables
• Dimensions first, then fact tables (with JOINs to dims)

Idempotency: running the same pipeline twice on the same day will not duplicate data — existing rows for today are deleted before re-inserting.`
      },
      {
        title: 'Pipeline versioning',
        content: `Every saved pipeline automatically gets version 1. You can save additional versions as you evolve your pipeline:

1. Go to Pipelines → select your pipeline
2. Click the "Versions" tab
3. Click "Save version" to snapshot the current state
4. Add a label (e.g. "v2 — added dim_product") and notes

Rollback: if a new version breaks something, click any previous version → "Restore this version" to revert.

Compare versions: select two versions to see a diff of what changed (tables added/removed, scripts changed).`
      },
      {
        title: 'Scheduling pipelines',
        content: `Automate your pipeline to run on a schedule:

1. Go to Scheduler
2. Click "Add schedule"
3. Select your pipeline
4. Choose frequency: hourly, daily, weekly, monthly, or custom
5. For custom schedules, set specific time, day, and timezone

The scheduler runs pipelines in the background. Check Pipeline Logs to see scheduled run results.

Note: the AIBridge server must be running for scheduled pipelines to execute. For production, deploy AIBridge as a service.`
      },
    ]
  },
  {
    section: 'Data Quality',
    icon: '✅',
    articles: [
      {
        title: 'Data quality checks',
        content: `AIBridge runs 3 levels of quality checks on staging data before loading to warehouse:

Level 1 — Null checks:
Scans for NULL values in critical columns. Rows with nulls in key columns are flagged.

Level 2 — Duplicate checks:
Detects fully duplicate rows (all columns identical). Duplicates are removed from staging and written to the audit log.

Level 3 — Business rules:
AI generates domain-specific rules (e.g. "price must be positive", "year must be between 1900 and current year"). Violations are flagged.

Quality score: the percentage of checks that passed. A score below 80% triggers a warning.

All quarantined records are stored in warehouse.dq_audit_log with the full row data and reason.`
      },
      {
        title: 'Audit log',
        content: `The audit log (warehouse.dq_audit_log) records every bad record that was quarantined before warehouse load.

Each record contains:
• pipeline_id — which pipeline found the issue
• run_id — which specific run
• table_name — which staging table
• column_name — which column had the issue
• issue_type — null_value, duplicate_key, or rule_violation
• reason — human-readable description
• row_data — the full JSON of the offending row
• check_date — when it was detected

Query in pgAdmin: SELECT * FROM warehouse.dq_audit_log ORDER BY check_date DESC;

The Data Quality page shows the audit log count and lets you filter by issue type.`
      },
    ]
  },
  {
    section: 'BI / Analytics',
    icon: '📊',
    articles: [
      {
        title: 'Natural language queries',
        content: `Go to BI / Analytics and type any question about your data in plain English:

Examples:
• "Average selling price by brand"
• "Top 10 most expensive models"
• "Monthly transaction count for last 6 months"
• "Compare manual vs automatic transmission prices"

AIBridge converts your question to SQL, runs it against your warehouse, and shows the results as a table and chart.

Refining results: use the refinement box to add conditions:
• "Only show cars from 2015 onwards"
• "Filter to diesel only"
• "Show top 5 instead of 10"
• "Add city column"

Each refinement modifies the existing SQL — it doesn't start from scratch.`
      },
      {
        title: 'Exporting reports',
        content: `Export query results as CSV, Excel, or PDF:

1. Run a query in BI / Analytics
2. Click the export button (⬇)
3. Choose format: CSV, Excel (.xlsx), or PDF
4. The file downloads immediately

Scheduling reports: go to Scheduler → Reports to run and export queries on a schedule automatically.`
      },
    ]
  },
  {
    section: 'Recovery Agent',
    icon: '🤖',
    articles: [
      {
        title: 'How the Recovery Agent works',
        content: `When a SQL script fails during pipeline execution, the Recovery Agent activates automatically:

1. It analyses the error message
2. Tries pattern-based fixes first (known common errors)
3. If that fails, asks the AI to rewrite the failing script
4. Applies the fix and retries execution
5. Logs the outcome to Recovery Logs

Common recoveries:
• Column name mismatches
• Missing tables
• Type cast errors
• ON CONFLICT clause issues

View recovery history: go to Recovery Agent in the left navigation to see all past recoveries, success rates, and fix methods used.`
      },
    ]
  },
  {
    section: 'AI Costs',
    icon: '💰',
    articles: [
      {
        title: 'Understanding AI cost tracking',
        content: `AIBridge tracks every AI API call and its cost:

What's tracked:
• Token usage (input + output)
• Cost in USD per call
• Peak vs off-peak pricing (DeepSeek charges 2× during peak hours: 9:30–11:30 UTC and 13:00–23:00 UTC)
• Agent name that made the call
• Pipeline that triggered it

Viewing costs:
Go to AI Costs to see:
• Total spend over any time period
• Cost breakdown by agent
• Individual call log with timestamps
• Current pricing mode (peak/off-peak)

Reducing costs: the schema cache avoids re-running AI for unchanged schemas. If you run the same pipeline with the same data, the second run costs $0 for Phase 1 and 2.`
      },
    ]
  },
]

export default function Help() {
  const [search, setSearch]         = useState('')
  const [activeSection, setSection] = useState(null)
  const [activeArticle, setArticle] = useState(null)

  const filtered = DOCS.map(sec => ({
    ...sec,
    articles: sec.articles.filter(a =>
      !search || a.title.toLowerCase().includes(search.toLowerCase()) ||
      a.content.toLowerCase().includes(search.toLowerCase())
    )
  })).filter(sec => sec.articles.length > 0)

  const current = activeSection !== null && activeArticle !== null
    ? DOCS[activeSection]?.articles[activeArticle]
    : null

  return (
    <>
      <PageHeader
        title="Help & Documentation"
        subtitle="Everything you need to know about AIBridge"
      />
      <PageBody>
        <div style={{ display: 'grid', gridTemplateColumns: '220px 1fr', gap: 20, height: '100%' }}>

          {/* Sidebar */}
          <div>
            <input
              value={search}
              onChange={e => { setSearch(e.target.value); setSection(null); setArticle(null) }}
              placeholder="Search docs..."
              style={{ width: '100%', padding: '7px 10px', fontSize: 12, border: '1px solid #e5e7eb', borderRadius: 6, marginBottom: 12, boxSizing: 'border-box' }}
            />
            {filtered.map((sec, si) => {
              const origIdx = DOCS.findIndex(d => d.section === sec.section)
              return (
                <div key={sec.section} style={{ marginBottom: 12 }}>
                  <div style={{ fontSize: 10, fontWeight: 600, color: '#aaa', textTransform: 'uppercase', letterSpacing: '.05em', padding: '4px 0', display: 'flex', alignItems: 'center', gap: 5 }}>
                    <span>{sec.icon}</span> {sec.section}
                  </div>
                  {sec.articles.map((art, ai) => {
                    const origAi = DOCS[origIdx].articles.findIndex(a => a.title === art.title)
                    const isActive = activeSection === origIdx && activeArticle === origAi
                    return (
                      <div key={art.title}
                        onClick={() => { setSection(origIdx); setArticle(origAi); setSearch('') }}
                        style={{ padding: '6px 8px', borderRadius: 5, fontSize: 12, cursor: 'pointer', marginBottom: 1, background: isActive ? '#E6F1FB' : 'transparent', color: isActive ? '#185FA5' : '#555', fontWeight: isActive ? 500 : 400 }}>
                        {art.title}
                      </div>
                    )
                  })}
                </div>
              )
            })}
          </div>

          {/* Content */}
          <div style={{ borderLeft: '1px solid #e5e7eb', paddingLeft: 24 }}>
            {!current ? (
              <div>
                <h2 style={{ fontSize: 18, fontWeight: 600, marginBottom: 4, color: '#111' }}>AIBridge Documentation</h2>
                <p style={{ fontSize: 13, color: '#888', marginBottom: 24, lineHeight: 1.6 }}>
                  Select a topic from the left, or search for what you need. New to AIBridge? Start with the Quick start guide.
                </p>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
                  {DOCS.map((sec, si) => (
                    <div key={sec.section}
                      onClick={() => { setSection(si); setArticle(0) }}
                      style={{ border: '1px solid #e5e7eb', borderRadius: 8, padding: '14px 16px', cursor: 'pointer', transition: 'border-color .15s' }}
                      onMouseEnter={e => e.currentTarget.style.borderColor = '#185FA5'}
                      onMouseLeave={e => e.currentTarget.style.borderColor = '#e5e7eb'}>
                      <div style={{ fontSize: 24, marginBottom: 8 }}>{sec.icon}</div>
                      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 3 }}>{sec.section}</div>
                      <div style={{ fontSize: 11, color: '#888' }}>{sec.articles.length} articles</div>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div>
                <div style={{ fontSize: 11, color: '#888', marginBottom: 8 }}>
                  {DOCS[activeSection].icon} {DOCS[activeSection].section}
                </div>
                <h2 style={{ fontSize: 17, fontWeight: 600, marginBottom: 16, color: '#111' }}>{current.title}</h2>
                <div style={{ fontSize: 13, color: '#374151', lineHeight: 1.85, whiteSpace: 'pre-wrap' }}>
                  {current.content}
                </div>

                {/* Related articles */}
                {DOCS[activeSection].articles.length > 1 && (
                  <div style={{ marginTop: 32, paddingTop: 16, borderTop: '1px solid #e5e7eb' }}>
                    <div style={{ fontSize: 11, fontWeight: 600, color: '#aaa', textTransform: 'uppercase', letterSpacing: '.05em', marginBottom: 8 }}>
                      More in {DOCS[activeSection].section}
                    </div>
                    {DOCS[activeSection].articles
                      .filter((_, i) => i !== activeArticle)
                      .map((art, i) => {
                        const origIdx = DOCS[activeSection].articles.findIndex(a => a.title === art.title)
                        return (
                          <div key={art.title}
                            onClick={() => setArticle(origIdx)}
                            style={{ padding: '7px 0', fontSize: 12, color: '#185FA5', cursor: 'pointer', borderBottom: '1px solid #f3f4f6' }}>
                            → {art.title}
                          </div>
                        )
                      })}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </PageBody>
    </>
  )
}
