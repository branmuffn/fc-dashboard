# Support Ledger Reconciliation Dashboard

**Live URL:** https://klrju2rpjcgffbf5yktsqp.streamlit.app/

### Challenge Requirements

**1. Hours Spent**
Approximately 1 hour total. 
* **15 mins:** Strategizing (evaluating the three challenge options, choosing Option C due to its alignment with data analytics and reconciliation workflows, and planning the pipeline).
* **35 mins:** Building the application (environment setup, writing the Pandas parsing engine, auditing the results for accuracy, and learning Streamlit to display the data clearly).
* **10 mins:** Deployment (learning how to push to GitHub and deploy via Streamlit Community Cloud) and drafting the handoff.

**2. The Hardest Decision**
The hardest decision was how to handle pledges that failed multiple conditions (e.g., an unparseable pledge that was also marked 'paused' and 'past end date'). I decided to implement a Strict Waterfall Categorization logic. Instead of evaluating them independently and risking double-counting exclusions, a pledge is only flagged for a condition if it hasn't already been disqualified by a more severe data error (like being unparseable).

**3. "Hacky" Pieces of Code**
There are two areas in the codebase that are a bit hacky:
* **Hardcoded Variables:** I hardcoded the exchange rates and `REFERENCE_DATE` directly into the top of `app.py`. In a real production environment, I would pull these from a dynamic configuration file, database, or an external API rather than leaving them statically declared in the main script.
* **Memory Inefficiency:** To create the 'Appendix' section at the bottom of the dashboard, I load and store a complete secondary copy of the raw `C_Pledges` and `C_Gifts` dataframes in memory. This is fine for a 50-row Excel sheet, but it is a memory-inefficient practice that would not scale for a ledger with millions of transactional rows.

**4. AI Usage**
I used Gemini to assist with generating the boilerplate Pandas data wrangling and learning the Streamlit components. I specifically stepped in to design the UX and progressive disclosure of the dashboard—ensuring it wasn't just a data dump, but a clean UI that allowed users to understand the KPIs at a glance and drill down into the anomalies. I also had to regularly override the AI to pace the workflow; I forced it to stop rushing into code generation before the overarching strategy, logic, and exact data requirements were fully clarified and locked in.