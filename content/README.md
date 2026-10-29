# Question bank

`demo.json` contains demonstration material, not an official or teacher-verified ЕНТ bank.
English material preserves the earlier prototype; Russian and Kazakh samples are illustrative.

Import: `python3 server.py import-bank /path/to/questions.json`
Validate without saving: `python3 server.py validate-bank /path/to/questions.json`
The input is an array in the same schema as demo.json. IDs must be unique and must not
collide with demo IDs. Each item has subject, language (en/ru/kk), topic, skill_id,
prompt, options (2–6 strings), correct_idx, explanation, and recheck with its own
prompt/options/correct_idx/explanation. Required top-level fields: id and status.
`status` is demo or reviewed. Reviewed items also require source (HTTPS URL),
license (permission to use), reviewed_by, reviewed_at (ISO date, not in the future).
Metadata is an operator assertion, not automatic verification of the source or accuracy.
Import never overwrites existing IDs. The imported bank is stored with the application data,
not in tracked source. Include this directory and the SQLite database in deployment backups.
Import trusted, licensed materials only; credentials are not part of question metadata.
