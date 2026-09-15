const fs=require('node:fs');
const path=require('node:path');
const sharp=require('../../../../artifacts/trotter-directions-site/node_modules/sharp');
const source=path.resolve(__dirname,'../theme-variations/world-window-round-02b.png');
const roi={left:50,top:120,width:490,height:360};
const add=(a,b)=>[a[0]+b[0],a[1]+b[1]],sub=(a,b)=>[a[0]-b[0],a[1]-b[1]],mul=(a,n)=>[a[0]*n,a[1]*n],dot=(a,b)=>a[0]*b[0]+a[1]*b[1];
const length=a=>Math.hypot(...a),norm=a=>mul(a,1/(length(a)||1)),distance=(a,b)=>length(sub(a,b));
const F=n=>Number(n.toFixed(3)),P=p=>p.map(F).join(' ');
function cubic(b,u){const v=1-u;return add(add(mul(b[0],v*v*v),mul(b[1],3*u*v*v)),add(mul(b[2],3*u*u*v),mul(b[3],u*u*u)));}
function bezier(points,u,t1,t2){
 const start=points[0],end=points.at(-1);let c00=0,c01=0,c11=0,x0=0,x1=0;
 for(let i=0;i<points.length;i++){const v=1-u[i],b1=3*u[i]*v*v,b2=3*u[i]*u[i]*v,a1=mul(t1,b1),a2=mul(t2,b2);const tmp=sub(points[i],add(mul(start,v*v*v+b1),mul(end,u[i]*u[i]*u[i]+b2)));c00+=dot(a1,a1);c01+=dot(a1,a2);c11+=dot(a2,a2);x0+=dot(a1,tmp);x1+=dot(a2,tmp);}
 const det=c00*c11-c01*c01;let a=det?(x0*c11-x1*c01)/det:0,b=det?(c00*x1-c01*x0)/det:0;
 const chord=distance(start,end);if(a<chord*1e-6||b<chord*1e-6)a=b=chord/3;
 return [start,add(start,mul(t1,a)),add(end,mul(t2,b)),end];
}
function fit(points,t1,t2,error=.65){
 if(points.length===2){const d=distance(points[0],points[1])/3;return [[points[0],add(points[0],mul(t1,d)),add(points[1],mul(t2,d)),points[1]]];}
 let u=[0];for(let i=1;i<points.length;i++)u.push(u.at(-1)+distance(points[i],points[i-1]));u=u.map(v=>v/u.at(-1));
 let curve,split=Math.floor(points.length/2),max;
 for(let iteration=0;iteration<5;iteration++){
  curve=bezier(points,u,t1,t2);max=0;
  for(let i=1;i<points.length-1;i++){const d=distance(points[i],cubic(curve,u[i]));if(d>max){max=d;split=i;}}
  if(max<=error)return [curve];if(max>error*4)break;
  u=u.map((v,i)=>{if(!i||i===points.length-1)return v;const a=mul(sub(curve[1],curve[0]),3),b=mul(sub(curve[2],curve[1]),3),c=mul(sub(curve[3],curve[2]),3),derivative=add(add(mul(a,(1-v)**2),mul(b,2*v*(1-v))),mul(c,v*v)),second=add(mul(sub(b,a),2*(1-v)),mul(sub(c,b),2*v)),diff=sub(cubic(curve,v),points[i]),denominator=dot(derivative,derivative)+dot(diff,second);return denominator?Math.max(0,Math.min(1,v-dot(diff,derivative)/denominator)):v;});
 }
 const center=norm(sub(points[split-1],points[split+1]));return [...fit(points.slice(0,split+1),t1,center,error),...fit(points.slice(split),mul(center,-1),t2,error)];
}
function corners(points){
 const n=points.length,scores=points.map((p,i)=>{let before=i,after=i,travel=0;while(travel<4){const next=(before-1+n)%n;travel+=distance(points[before],points[next]);before=next;}travel=0;while(travel<4){const next=(after+1)%n;travel+=distance(points[after],points[next]);after=next;}return Math.acos(Math.max(-1,Math.min(1,dot(norm(sub(p,points[before])),norm(sub(points[after],p))))));});
 const picked=[];for(const i of scores.map((score,i)=>[score,i]).sort((a,b)=>b[0]-a[0]).filter(([score])=>score>.70).map(([,i])=>i)){if(!picked.some(j=>distance(points[i],points[j])<6))picked.push(i);}
 if(picked.length<2){let left=0;points.forEach((p,i)=>{if(p[0]<points[left][0])left=i;});let far=0;points.forEach((p,i)=>{if(distance(p,points[left])>distance(points[far],points[left]))far=i;});return [left,far].sort((a,b)=>a-b);}
 return picked.sort((a,b)=>a-b);
}
function area(points){let a=0;for(let i=0;i<points.length;i++){const p=points[i],q=points[(i+1)%points.length];a+=p[0]*q[1]-q[0]*p[1];}return a/2;}
(async()=>{
 const {data,info}=await sharp(source).extract(roi).raw().toBuffer({resolveWithObject:true});
 const get=(x,y)=>{const i=(y*info.width+x)*info.channels;return data[i+2]-data[i]-39;};
 const nodes=new Map(),links=new Map();
 const pairs={1:[[0,3]],2:[[0,1]],3:[[3,1]],4:[[1,2]],5:[[0,3],[1,2]],6:[[0,2]],7:[[3,2]],8:[[2,3]],9:[[0,2]],10:[[0,1],[2,3]],11:[[1,2]],12:[[3,1]],13:[[0,1]],14:[[0,3]]};
 for(let y=0;y<info.height-1;y++)for(let x=0;x<info.width-1;x++){
  const values=[get(x,y),get(x+1,y),get(x+1,y+1),get(x,y+1)];const code=values.reduce((n,v,i)=>n+(v>=0?1<<i:0),0);if(!pairs[code])continue;
  const edgePoints=[[[x,y],[x+1,y]],[[x+1,y],[x+1,y+1]],[[x,y+1],[x+1,y+1]],[[x,y],[x,y+1]]];
  const edgeKey=[`h${x},${y}`,`v${x+1},${y}`,`h${x},${y+1}`,`v${x},${y}`];
  for(const [a,b]of pairs[code]){for(const e of[a,b]){const[p,q]=edgePoints[e],vp=get(...p),vq=get(...q),t=vp/(vp-vq);nodes.set(edgeKey[e],[p[0]+(q[0]-p[0])*t+.5+roi.left,p[1]+(q[1]-p[1])*t+.5+roi.top]);}links.set(edgeKey[a],[...(links.get(edgeKey[a])||[]),edgeKey[b]]);links.set(edgeKey[b],[...(links.get(edgeKey[b])||[]),edgeKey[a]]);}
 }
 const visited=new Set(),contours=[];
 for(const start of nodes.keys()){if(visited.has(start))continue;let current=start,prior=null;const points=[];while(!visited.has(current)){visited.add(current);points.push(nodes.get(current));const next=links.get(current).find(key=>key!==prior);prior=current;current=next;}if(Math.abs(area(points))>8)contours.push(points);}
 contours.sort((a,b)=>Math.abs(area(b))-Math.abs(area(a)));
 const paths=contours.map((points,index)=>{const cornersAt=corners(points);const curves=[];for(let j=0;j<cornersAt.length;j++){const start=cornersAt[j],end=cornersAt[(j+1)%cornersAt.length],segment=end>start?points.slice(start,end+1):[...points.slice(start),...points.slice(0,end+1)];curves.push(...fit(segment,norm(sub(segment[1],segment[0])),norm(sub(segment.at(-2),segment.at(-1)))));}const d=`M${P(curves[0][0])}${curves.map(c=>`C${P(c[1])} ${P(c[2])} ${P(c[3])}`).join('')}Z`;return {index,area:Math.abs(area(points)),points:points.length,corners:cornersAt.length,curves:curves.length,d};});
 const svg=`<svg xmlns="http://www.w3.org/2000/svg" viewBox="64 147 450 333" fill="currentColor"><title>Trotter R07</title>${paths.map(p=>`<path d="${p.d}"/>`).join('')}</svg>\n`;
 fs.writeFileSync(path.join(__dirname,'r07.svg'),svg);
 fs.writeFileSync(path.join(__dirname,'contours.json'),JSON.stringify(paths,null,2));
 const preview=svg.replace('fill="currentColor"','fill="currentColor" color="#427494"');
 await sharp(Buffer.from(preview)).resize({width:1350,height:999}).png().toFile(path.join(__dirname,'r07-preview.png'));
 await sharp(Buffer.from(preview)).resize({width:450,height:333}).flatten({background:'#faf8f2'}).png().toFile(path.join(__dirname,'r07-proof.png'));
 console.log(paths.map(({d,...stats})=>stats));
 console.log(`SVG bytes: ${Buffer.byteLength(svg)}`);
})();
