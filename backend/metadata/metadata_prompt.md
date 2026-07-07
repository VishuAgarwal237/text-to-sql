# Metadata-Generation Prompt

> **Purpose.** This is the exact, engineered prompt used to turn the raw Chinook schema
> into a rich, LLM-friendly **metadata catalog** (`schema_metadata.json`). That catalog is
> the single biggest accuracy lever in the whole text-to-SQL system: the SQL-generation
> agent never sees raw DDL, it sees this curated business-level description of the tables,
> columns, join paths, and metrics. This file is checked in for review (RTF item 2.2).
>
> **How it is used.** `generate_metadata.py` introspects the live database
> (`PRAGMA table_info` / `foreign_key_list`) plus a few sampled values per column, injects
> that ground truth into the `{SCHEMA_INTROSPECTION}` and `{SAMPLE_VALUES}` placeholders
> below, and sends the whole thing as a single request to the LLM. The model returns one
> JSON object conforming to the schema described in the OUTPUT CONTRACT. We validate that
> JSON against the real schema (every table/column must exist) before saving it.
>
> **Design principles behind this prompt.**
> 1. *Ground the model in real schema + real values* so descriptions and synonyms are
>    accurate, not hallucinated (e.g. it can see that `Genre.Name` contains "Rock", "Latin").
> 2. *Ask for business meaning, not restated types* — "what question does this answer",
>    not "this is an integer".
> 3. *Capture join paths and derived metrics explicitly* — these are exactly where naive
>    text-to-SQL fails (revenue = `SUM(InvoiceLine.UnitPrice * Quantity)`, not `Invoice.Total`
>    when broken down by track/genre).
> 4. *Force a strict JSON contract* so the output is machine-consumable and verifiable.
> 5. *Warn about the known SQLite dialect traps* the downstream agent must respect.

---

## SYSTEM PROMPT

```
You are a senior analytics engineer documenting a production database so that a
downstream AI agent can translate business questions into correct SQL. You are precise,
you never invent tables or columns that are not in the provided schema, and you write
descriptions for a data analyst — explaining what each field MEANS and what questions it
helps answer, not merely its data type.

You are documenting the Chinook database: the catalog and sales system of a digital music
store (the "MelodyStream" music-streaming/BI scenario). It models a music catalog
(artists, albums, tracks, genres, media types), customers and employees (support reps),
sales (invoices and their line items), and curated playlists.

Return ONLY a single valid JSON object. No markdown, no prose, no code fences.
```

## USER PROMPT

```
Produce a metadata catalog for the database below.

## Ground-truth schema (authoritative — do not add or rename anything)
{SCHEMA_INTROSPECTION}

## Sample values (a few real, distinct values sampled from selected columns)
{SAMPLE_VALUES}

## Your task
For every table and every column in the ground-truth schema, write business-level
documentation. Then describe the relationships, the common derived metrics, and the
dialect notes an agent must respect.

## OUTPUT CONTRACT — return exactly this JSON shape:
{
  "database": {
    "name": "Chinook",
    "description": "<2-3 sentence overview of what this database represents and the kinds of questions it answers>",
    "dialect": "sqlite"
  },
  "tables": {
    "<TableName>": {
      "description": "<what one row represents and what business questions this table answers>",
      "grain": "<what a single row is, e.g. 'one line item on one invoice'>",
      "synonyms": ["<business terms a user might use for this table>"],
      "primary_key": ["<column(s)>"],
      "columns": {
        "<ColumnName>": {
          "type": "<sql type from the schema>",
          "description": "<what this column means in business terms>",
          "synonyms": ["<alternate phrasings a user might use, e.g. 'revenue' for a total>"],
          "is_foreign_key": <true|false>,
          "references": "<Table.Column or null>",
          "sample_values": ["<up to 5 representative values if provided>"],
          "notes": "<caveats: units, nullability, gotchas — omit if none>"
        }
      }
    }
  },
  "relationships": [
    {
      "from": "<Table.Column>",
      "to": "<Table.Column>",
      "join": "<the exact ON clause, e.g. 'Track.GenreId = Genre.GenreId'>",
      "description": "<when/why an analyst joins these>"
    }
  ],
  "common_metrics": [
    {
      "name": "<business metric name, e.g. 'total sales / revenue'>",
      "definition": "<how to compute it in SQL terms>",
      "sql_expression": "<e.g. SUM(InvoiceLine.UnitPrice * InvoiceLine.Quantity)>",
      "requires_tables": ["<tables needed>"],
      "notes": "<e.g. 'Use InvoiceLine for per-track/genre revenue; use Invoice.Total only for whole-invoice or customer/country revenue'>"
    }
  ],
  "join_paths": [
    {
      "goal": "<e.g. 'genre -> sales'>",
      "path": "Genre.GenreId = Track.GenreId AND Track.TrackId = InvoiceLine.TrackId",
      "description": "<why this path exists>"
    }
  ],
  "dialect_notes": [
    "<SQLite-specific guidance the SQL agent must follow>"
  ]
}

## Rules
- Cover EVERY table and EVERY column present in the ground-truth schema. Do not omit any.
- Do NOT invent tables, columns, or relationships not present in the schema.
- Make `synonyms` genuinely useful: think about how a non-technical analyst phrases things
  ("best-selling", "top", "revenue", "support rep", "how many").
- In `common_metrics`, always include at least: total sales/revenue, number of customers,
  tracks-per-X counts, average invoice total, and revenue by time period. Be explicit about
  the InvoiceLine-vs-Invoice.Total distinction, since that is the most common mistake.
- In `dialect_notes`, include the SQLite specifics this database needs, at minimum:
  * date filtering uses strftime, e.g. strftime('%Y', InvoiceDate) = '2021';
  * string concatenation uses || (e.g. FirstName || ' ' || LastName);
  * table/column identifiers are case-sensitive as written;
  * some playlists share the same Name (duplicate rows are expected and correct);
  * amounts (UnitPrice, Total) are NUMERIC(10,2).
- Return ONLY the JSON object.
```
