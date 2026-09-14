import {PAGE_WIDTH as W,PAGE_HEIGHT as H,BOOK_MARGIN as M} from './passport-paper';
import {PAPER_CLEARANCE} from './passport-canvas';

const clamp=(value:number)=>Math.max(0,Math.min(1,value));
type CoverGrab={x:number;start:number;last:number;time:number;moved:boolean;tapOpens:boolean};

// One stiff panel: a single hinge angle, with no page-fold geometry.
export class PassportCoverController {
 progress:number;target:0|1;settled:0|1;velocity=0;settling=false;grab:CoverGrab|null=null;
 private elapsed=0;
 constructor(closed:boolean){this.progress=closed?0:1;this.target=this.settled=this.progress as 0|1;}
 get busy(){return this.settling||this.grab!==null;}
 get blocksPages(){return this.progress!==1||this.busy;}
 begin(x:number,time:number){
  if(this.grab)return;
  this.grab={x,start:this.progress,last:this.progress,time,moved:this.settling,tapOpens:this.progress===0&&!this.settling};
  this.settling=false;this.velocity=0;
 }
 move(x:number,time:number){
  const g=this.grab;if(!g)return;
  const delta=g.x-x;if(!g.moved&&Math.abs(delta)<5)return;
  g.moved=true;
  const next=clamp(g.start+delta/(W*1.5)),dt=Math.max(8,Math.min(64,time-g.time));
  this.velocity=.55*this.velocity+.45*(next-g.last)/dt;
  this.progress=next;g.last=next;g.time=time;
 }
 release(cancel=false,instant=false,time=0){
  const g=this.grab;if(!g)return;this.grab=null;
  if(time-g.time>100)this.velocity=0;
  const open=cancel?this.settled:!g.moved?(g.tapOpens?1:this.settled):Math.abs(this.velocity)>.0008?(this.velocity>0?1:0):(this.progress>=.5?1:0);
  this.go(open,instant);
 }
 go(target:0|1,instant=false){
  this.grab=null;this.target=target;this.elapsed=0;
  if(instant||this.progress===target){this.snap(target);return;}
  this.settling=true;
 }
 snap(target:0|1){this.progress=this.target=this.settled=target;this.velocity=0;this.settling=false;this.grab=null;}
 advance(dt:number){
  if(!this.settling)return;
  dt=Math.max(1,Math.min(32,dt));this.elapsed+=dt;
  // More weight and damping than the paper; never bounce through the cover stop.
  const rate=.018,decay=Math.exp(-rate*dt),delta=this.progress-this.target,term=(this.velocity+rate*delta)*dt;
  this.progress=clamp(this.target+(delta+term)*decay);this.velocity=(this.velocity-rate*term)*decay;
  if(Math.abs(this.progress-this.target)<.0015&&Math.abs(this.velocity)<.00008||this.elapsed>700)this.snap(this.target);
 }
}

// Center the silhouette: keep the spine still until the panel passes upright.
export function coverOffset(progress:number){return -W/2-Math.min(0,W*Math.cos(Math.PI*clamp(progress)))/2;}

export function passportPose(progress:number,renderedWidth=410){
 const p=clamp(progress),width=W*2+M*2;
 // CSS perspective is measured in viewport pixels. Include the thick board's
 // projected corners when fitting the moving silhouette, not just its flat
 // cos(angle) width. Otherwise the near edge escapes the WebView at ~75–90%.
 const distance=1000*width/Math.max(1,renderedWidth),angle=Math.PI*p;
 const corners=[-4,W+4].flatMap(x=>[-4,H+4].map(y=>{
  const ratio=distance/(distance-x*Math.sin(angle));
  return {x:x*Math.cos(angle)*ratio,y:H/2+(y-H/2)*ratio};
 }));
 const left=Math.min(-4,...corners.map(c=>c.x)),right=Math.max(W+4,...corners.map(c=>c.x));
 const minY=Math.min(-4,...corners.map(c=>c.y)),maxY=Math.max(H+4,...corners.map(c=>c.y));
 const scale=Math.min(1+.65*(1-p*p*(3-2*p)),(width-16)/(right-left));
 const paperRoom=PAPER_CLEARANCE*p*p*p;
 const top=Math.max(M-minY*scale,paperRoom);
 return {scale,offset:-(left+right)/2,top,height:top+H*scale+Math.max(M+(maxY-H)*scale,paperRoom),width};
}
// A stable drawable viewport lets native layout catch up without ever cutting
// the moving cover. Flow height remains independent and can stay compact.
export function passportViewportHeight(renderedWidth:number){
 let height=0;
 for(let step=0;step<=100;step++){
  const pose=passportPose(step/100,renderedWidth);
  height=Math.max(height,renderedWidth*pose.height/pose.width);
 }
 return Math.ceil(height+24);
}
export function passportPoint(x:number,y:number,progress:number,renderedWidth=410){
 const pose=passportPose(progress,renderedWidth);return {x:(x-pose.width/2)/pose.scale+W-pose.offset,y:(y-pose.top)/pose.scale};
}
