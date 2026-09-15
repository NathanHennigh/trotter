const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const mime={'.html':'text/html; charset=utf-8','.png':'image/png','.svg':'image/svg+xml','.md':'text/plain; charset=utf-8'};
http.createServer((req,res)=>{
  let name;
  try { name=decodeURIComponent(new URL(req.url,'http://localhost').pathname); } catch { res.writeHead(400).end();return; }
  name=name==='/'?'index.html':name.slice(1);
  if(name!==path.basename(name)||!mime[path.extname(name)]){res.writeHead(404).end();return;}
  fs.readFile(path.join(__dirname,name),(err,data)=>{
    if(err){res.writeHead(404).end();return;}
    res.writeHead(200,{'Content-Type':mime[path.extname(name)],'Cache-Control':'no-store'});res.end(data);
  });
}).listen(8766,'127.0.0.1',()=>process.stdout.write('Logo gallery ready: http://127.0.0.1:8766\n'));
