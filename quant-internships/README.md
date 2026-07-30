# Summer 2027 quant internships

A single static page listing every Summer 2027 quantitative trading, research and developer
internship open to an undergraduate graduating **May 2028**, with direct application links,
posted compensation, and each firm's one-application policy.

Built the same way as the other sites in `~/Desktop/Code`: static HTML, one token-based
stylesheet, one vanilla-JS IIFE. No framework, no bundler, no `package.json`.

```
index.html          markup, filter controls, table shell, notes
assets/style.css    design tokens + all styling; light and dark via [data-theme]
assets/app.js       filtering, sorting, search, applied-tracking (one IIFE)
assets/data.js      the roles themselves — this is the only file you normally edit
favicon.svg
```

## Running it

Any static server. The one wired into `.claude/launch.json` is:

```bash
node -e "const http=require('http'),fs=require('fs'),path=require('path');const ROOT='/Users/andrewpark/Desktop/Code/quant-internships';const T={'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml'};http.createServer((q,r)=>{let p=decodeURIComponent(q.url.split('?')[0]);if(p==='/')p='/index.html';const fp=path.join(ROOT,p);fs.readFile(fp,(e,d)=>{if(e){r.writeHead(404);r.end('not found');return;}r.writeHead(200,{'content-type':T[path.extname(fp)]||'application/octet-stream','cache-control':'no-store'});r.end(d);});}).listen(8944,()=>console.log('http://localhost:8944'));"
```

## Editing the data

Every row in `assets/data.js` is one posting. The field contract is documented in the header
comment of that file. Three rules matter:

1. **Never invent a URL or a compensation figure.** An empty string renders as "not disclosed",
   which is honest. A guess is not.
2. **`comp_source` must be `"posted"` or `"reported"`.** Posted means it was in the job
   description, usually because a pay-transparency law forced it. Reported means levels.fyi,
   Glassdoor or similar. The page shows this under every figure so the reader can weight it.
3. **`id` is permanent.** It keys the local "applied" flag in `localStorage`. Reusing an id
   silently transfers a checkmark to a different job.

PhD- and Master's-only postings are deliberately absent. The exclusions are listed by name in
the `data.js` header so a future update doesn't "rediscover" them.

`one_only: true` drives the red flag in the Multi-apply column. Set it only for genuine
restrictions — "bundle several roles in one application" is permissive and must not be flagged.

## Ordering

The default sort is QT before QR before QD, then tier, then New York first, then the order rows
appear in `data.js`. That last key is deliberate: within a tier, curation order carries judgement
that alphabetical sorting would throw away. Reorder rows in the file to change it.

Tier is a rough read on selectivity and exit value, not a ranking of the firms as businesses.

## Verification

Data checked **30 July 2026** against firm-hosted career pages, Greenhouse/Lever/Ashby boards, and
<https://github.com/northwesternfintech/2027QuantInternships>. Postings close without notice;
the footer says so, and it should stay there.

All 59 application links were resolved with `curl -L` and return 200. The three Citadel URLs return
403 to any automated request (Cloudflare) and were confirmed by loading them in a real browser
instead — do not "fix" them on the strength of a failing HEAD check.

To re-check the links after editing:

```bash
python3 -c "
import re,subprocess,concurrent.futures
urls=re.findall(r'apply_url:\s*\"(https://[^\"]+)\"',open('assets/data.js').read())
f=lambda u:(subprocess.run(['curl','-s','-o','/dev/null','-w','%{http_code}','-L','--max-time','20',u],capture_output=True,text=True).stdout,u)
[print(c,u) for c,u in concurrent.futures.ThreadPoolExecutor(12).map(f,urls) if c!='200']
"
```

## Keyboard

`/` focus search · `Esc` clear · `1` `2` `3` toggle QT/QR/QD · `0` reset · click a column header to sort.
