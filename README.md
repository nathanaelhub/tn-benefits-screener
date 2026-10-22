# tn-benefits-screener

A cited Tennessee benefits screener (SNAP, WIC, TennCare/CoverKids) for Claude. Plain code does the
eligibility arithmetic from official tables; Claude does the conversation. Work in progress.

`tn-screener sources fetch` downloads the official documents the rules cite into
`src/tn_screener/data/sources/text/`.
