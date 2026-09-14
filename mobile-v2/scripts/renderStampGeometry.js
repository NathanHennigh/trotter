const fs = require('fs'), path = require('path'), ts = require('typescript'), { execFileSync } = require('child_process');
const root=path.join(__dirname,'..'), dir=path.join(root,'src/components/trotter/stamps');
function load(file){const m={exports:{}};new Function('module','exports',ts.transpileModule(fs.readFileSync(path.join(dir,file),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText)(m,m.exports);return m.exports;}
const {resolveStampGeometry}=load('stampGeometry.ts'), {fitFontSize}=load('stampLayout.ts');
const bundles=JSON.parse(fs.readFileSync(path.join(dir,'stampTemplates.json'),'utf8'));
const shapes={archedCountryCanonical:'01_arched_country_canonical',archedCountryBanner:'01_arched_country_banner',archedCountryVariant:'01_arched_country_variant',circularCityClean:'02_circular_city_clean',circularCityDoubleLine:'02_circular_city_double_line',roundedImmigrationCanonical:'03_rounded_immigration_canonical',roundedImmigrationWithBand:'03_rounded_immigration_with_band',shieldBadgeRounded:'04_shield_badge_rounded'};
const image=(folder,file,x,y,w,h)=>`<image href="data:image/png;base64,${fs.readFileSync(path.join(root,'assets/processed',folder,file+'.png')).toString('base64')}" x="${x}" y="${y}" width="${w}" height="${h}"/>`;
const escape=s=>s.replaceAll('&','&amp;').replaceAll('<','&lt;');
const W=204.75,H=165.75;
function stamp(shape,country,id){const t=resolveStampGeometry(shape,bundles[shape].default,W,H),p=t.frame;
let svg=image('stamp-shapes',shapes[shape],p.left*W,p.top*H,p.width*W,p.height*H);
const art=country==='CUBA'?'11_cuba_havana-capitol':country==='SOMALILAND'?'81_somaliland_laas-geel':'13_dominican_republic_puerta_del_conde';
const i=t.icon;svg+=image('country-icons',art,i.left*W,i.top*H,i.width*W,i.height*H);
const b=t.country,w=b.width*W,h=b.height*H;
let fontSize=fitFontSize(country,22.75*(b.fontScale??1),w,h,b,W),d;
if(t.titleMode==='arc'){fontSize=fitFontSize(country,22.75*(b.fontScale??1),w*.84,h*.85,b,W);const depth=Math.max(.2,Math.min(1.5,t.arcDepth??.7)),left=b.left*W,top=b.top*H,startY=top+h*Math.min(.88,.6+depth*.15),mid=top+h*Math.max(.06,.52-depth*.34),c=mid-(startY-mid)*.4;d=`M ${left+w*.08} ${startY} C ${left+w*.25} ${c}, ${left+w*.75} ${c}, ${left+w*.92} ${startY}`;}
if(t.titleMode==='circleArc'){const r=Math.min(p.width*W,p.height*H)*(t.circleTitleRadius??.28),cx=(p.left+p.width/2)*W,cy=(p.top+p.height*(.5+(t.arcCenterYOffset??0)))*H,a=70*Math.PI/180,x=Math.sin(a)*r,y=cy-Math.cos(a)*r;d=`M ${cx-x} ${y} A ${r} ${r} 0 0 1 ${cx+x} ${y}`;fontSize=fitFontSize(country,22.75*(b.fontScale??1),r*a*1.8,h*.7,b,W);}
svg+=d?`<defs><path id="${id}" d="${d}"/></defs><text font-size="${fontSize}" font-weight="700" text-anchor="middle" letter-spacing="${b.tracking??0}"><textPath xlink:href="#${id}" startOffset="50%">${escape(country)}</textPath></text>`:`<text x="${(b.left+b.width/2)*W}" y="${(b.top+b.height/2)*H}" font-size="${fontSize}" font-weight="700" text-anchor="middle" dominant-baseline="central">${escape(country)}</text>`;
for(const [key,text,base] of [['airport',country==='CUBA'?'HAV':country==='SOMALILAND'?'HGA':'PUJ',12.2],['date','18 DEC 2022',13.16]]){const b=t[key],fs=fitFontSize(text,base*(b.fontScale??1),b.width*W,b.height*H,b,W);svg+=`<text x="${(b.left+b.width/2)*W}" y="${(b.top+b.height/2)*H}" font-family="monospace" font-size="${fs}" text-anchor="middle" dominant-baseline="central">${text}</text>`;}
return svg;}
(async()=>{let all='';let n=0;for(const shape of Object.keys(shapes)){for(const country of ['CUBA','SOMALILAND','DOMINICAN REPUBLIC']){const x=n%3*320,y=Math.floor(n/3)*275;all+=`<g transform="translate(${x+5} ${y+32}) scale(1.5)">${stamp(shape,country,'p'+n)}</g><text x="${x+8}" y="${y+18}" font-size="12">${shape}</text>`;n++;}}
const svg=`<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="960" height="2200" font-family="Arial" fill="#342c22"><rect width="960" height="2200" fill="#f6eddc"/>${all}</svg>`;
const out=path.join(root,'qa-screens','stamp-geometry-calibration.png');fs.writeFileSync(out.replace('.png','.svg'),svg);execFileSync('python',['-c', 'import sys,cairosvg;cairosvg.svg2png(url=sys.argv[1],write_to=sys.argv[2])',out.replace('.png','.svg'),out]);console.log(out);})();

