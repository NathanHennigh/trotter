import {passportMaterial} from './passport-material';
import {FlipCalculation} from './page-fold/fold-geometry.js';
import {PAGE_WIDTH as W,PAGE_HEIGHT as H,BOOK_MARGIN as M,type PageTexture} from './passport-paper';
export type Point={x:number;y:number};
export type PaperFold={direction:1|-1;corner:'top'|'bottom';point:Point;spread:number};
// Space for a lifted sheet and its shadow, without moving the resting book
// underneath the finger as the fold changes shape.
export const PAPER_CLEARANCE=72;
export function drawPassport(c:CanvasRenderingContext2D,textures:PageTexture[],spread:number,fold:PaperFold|null,dpr:number,cover?:{offset:number;progress:number;scale:number;height:number},variant='lounge',top=M){
 const material=passportMaterial(variant),gutter=material.gutter;
 c.setTransform(dpr,0,0,dpr,0,0);c.clearRect(0,0,c.canvas.width/dpr,c.canvas.height/dpr);c.save();c.translate(W+M,top);c.scale(cover?.scale??1,cover?.scale??1);c.translate(-W,0);
 const board=(left:number,width:number)=>{c.fillStyle=material.cover;c.strokeStyle=material.edge;c.lineWidth=1;c.beginPath();c.roundRect(left-4,-4,width+8,H+8,5);c.fill();c.stroke();};
 if(cover){
  c.translate(cover.offset,0);board(W,W);
  for(let i=3;i>0;i--){c.fillStyle=i%2?material.paperEdge:material.paper;c.fillRect(W,H+i-3,W+i,3);}
  c.fillStyle=material.paper;c.fillRect(W,0,W,H);
  if(textures[spread*2+1])c.drawImage(textures[spread*2+1].canvas,W,0,W,H);
  const spine=c.createLinearGradient(W,0,W+14,0);spine.addColorStop(0,`rgba(${gutter},.29)`);spine.addColorStop(.2,`rgba(${gutter},.09)`);spine.addColorStop(1,`rgba(${gutter},0)`);c.fillStyle=spine;c.fillRect(W,0,14,H);
  const shade=c.createLinearGradient(W,0,W+W*.8,0);shade.addColorStop(0,`rgba(39,31,20,${.18*Math.sin(Math.PI*cover.progress)})`);shade.addColorStop(1,'#30291b00');
  c.fillStyle=shade;c.fillRect(W,0,W,H);c.restore();return;
 }
 board(0,W*2);
 for(let i=3;i>0;i--){c.fillStyle=i%2?material.paperEdge:material.paper;c.fillRect(-i,H+i-3,W*2+i*2,3);}
 const image=(index:number,x:number)=>{if(textures[index])c.drawImage(textures[index].canvas,x,0,W,H);};
 image(spread*2,0);image(spread*2+1,W);
 const seam=()=>{const shadow=c.createLinearGradient(W-14,0,W+14,0);shadow.addColorStop(0,`rgba(${gutter},0)`);shadow.addColorStop(.40,`rgba(${gutter},.08)`);shadow.addColorStop(.5,`rgba(${gutter},.29)`);shadow.addColorStop(.58,`rgba(${gutter},.10)`);shadow.addColorStop(1,`rgba(${gutter},0)`);c.fillStyle=shadow;c.fillRect(W-14,0,28,H);};
 if(!fold){seam();c.restore();return;}
 const calc=new FlipCalculation(fold.direction===1?0:1,fold.corner,String(W),String(H));
 if(!calc.calc(fold.point)){seam();c.restore();return;}
 const global=(p:Point)=>({x:W+(fold.direction===1?p.x:-p.x),y:p.y});
 const path=(points:(Point|null)[])=>{c.beginPath();let first=true;for(const point of points){if(!point)continue;const p=global(point);if(first)c.moveTo(p.x,p.y);else c.lineTo(p.x,p.y);first=false;}c.closePath();};
 const under=fold.direction===1?spread*2+3:spread*2-2,back=fold.direction===1?spread*2+2:spread*2-1;
 c.save();path(calc.getBottomClipArea());c.clip();image(under,fold.direction===1?W:0);c.restore();seam();
 const polygon=calc.getFlippingClipArea();
 c.save();path(polygon);c.shadowColor='#302a2938';c.shadowBlur=13;c.shadowOffsetX=fold.direction===1?-3:3;c.shadowOffsetY=4;c.fillStyle=material.paper;c.fill();c.restore();
 c.save();path(polygon);c.clip();const position=global(calc.getActiveCorner());c.translate(position.x,position.y);c.rotate(calc.getAngle());image(back,0);c.restore();
 const start=calc.getShadowStartPoint(),progress=calc.getFlippingProgress()/100;let angle=NaN;try{angle=calc.getShadowAngle();}catch{/* A flat fold has no shadow line. */}
 if(start&&Number.isFinite(angle)){
  const width=12+34*Math.sin(progress*Math.PI),p=global(start);c.save();path(polygon);c.clip();c.translate(p.x,p.y);c.rotate(Math.PI+angle+Math.PI/2);
  const x=fold.direction===1?-width:0,g=c.createLinearGradient(x,0,x+width,0);
  if(fold.direction===1){g.addColorStop(0,'#00000000');g.addColorStop(.67,'#49402108');g.addColorStop(.9,'#ffffff50');g.addColorStop(1,'#4c402631');}
  else{g.addColorStop(0,'#4c402631');g.addColorStop(.1,'#ffffff50');g.addColorStop(.33,'#49402108');g.addColorStop(1,'#00000000');}
  c.fillStyle=g;c.fillRect(x,-H*2,width,H*4);c.restore();
 }
 c.restore();
}
export function clampFold(point:Point,corner:'top'|'bottom'):Point|null{
 const c=new FlipCalculation(0,corner,String(W),String(H));
 if(!c.calc(point))return null;
 const position={...c.getPosition()},edge=corner==='top'?2:H-2;
 const fits=()=>c.getFlippingClipArea().every((p:Point|null)=>!p||p.x>=-W&&p.x<=W&&p.y>=-PAPER_CLEARANCE+20&&p.y<=H+PAPER_CLEARANCE-20);
 if(fits())return position;
 // Extremely diagonal/outside drags can throw a whole page out of the book.
 // Limit the lift continuously, retaining horizontal travel and the turn's
 // direction; do not clip the rendered sheet at the canvas boundary.
 let low=0,high=1,result:Point|null=null;
 for(let i=0;i<14;i++){
  const amount=(low+high)/2,next={x:position.x,y:edge+(position.y-edge)*amount};
  if(c.calc(next)&&fits()){low=amount;result={...c.getPosition()};}else high=amount;
 }
 return result;
}
export function foldTarget(complete:boolean,corner:'top'|'bottom'){return {x:complete?-W+2:W-2,y:corner==='top'?2:H-2};}
export function shouldFinishFold(point:Point,velocity:number){return Math.abs(velocity)>.65?velocity<0:point.x<0;}
