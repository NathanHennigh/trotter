import {PAGE_WIDTH as W,PAGE_HEIGHT as H} from './passport-paper';
import {clampFold,foldTarget,shouldFinishFold,type Point,type PaperFold} from './passport-canvas';
type Grab={start:Point;base:Point;direction:1|-1;corner:'top'|'bottom';last:Point;time:number;moved:boolean};
export class PassportController {
 spread:number;fold:PaperFold|null=null;grab:Grab|null=null;velocity:Point={x:0,y:0};settling=false;
 private queued:1|-1|null=null;private target:Point|null=null;private commit=false;private elapsed=0;
 constructor(public spreads:number,initial=0){this.spread=Math.max(0,Math.min(spreads-1,initial));}
 begin(point:Point,time:number){
  if(this.grab||point.x<0||point.x>W*2||point.y<0||point.y>H)return false;
  const direction=this.fold?.direction??(point.x<W?-1:1),corner=this.fold?.corner??(point.y<H/2?'top':'bottom');
  const canTurn=this.spread+direction>=0&&this.spread+direction<this.spreads;
  const base=this.fold?.point??foldTarget(false,corner);
  this.grab={start:point,base:{...base},direction,corner,last:{...base},time,moved:Boolean(this.fold)};
  this.settling=false;this.target=null;this.queued=null;this.velocity={x:0,y:0};return canTurn;
 }
 move(point:Point,time:number){
  const g=this.grab;if(!g)return;
  const dx=(point.x-g.start.x)*g.direction,dy=point.y-g.start.y;
  if(!g.moved&&Math.hypot(dx,dy)<5)return;
  g.moved=true;
  if(this.spread+g.direction<0||this.spread+g.direction>=this.spreads)return;
  const next=clampFold({x:Math.min(W-1,Math.max(-W+1,g.base.x+dx)),y:g.base.y+dy},g.corner);if(!next)return;
  const dt=Math.max(8,Math.min(64,time-g.time));this.velocity={x:this.velocity.x*.5+(next.x-g.last.x)/dt*.5,y:this.velocity.y*.5+(next.y-g.last.y)/dt*.5};
  this.fold={spread:this.spread,direction:g.direction,corner:g.corner,point:next};g.last=next;g.time=time;
 }
 release(cancel=false,reduced=false,time=0){
  const g=this.grab;this.grab=null;if(!g)return false;
  if(!this.fold)return g.moved;
  if(time-g.time>100)this.velocity={x:0,y:0};
  this.settle(!cancel&&shouldFinishFold(this.fold.point,this.velocity.x),reduced);return true;
 }
 settle(complete:boolean,reduced=false){if(!this.fold)return;this.commit=complete;this.target=foldTarget(complete,this.fold.corner);this.elapsed=0;this.settling=true;if(reduced)this.finish();}
 settleForCover(instant=false,returnToCurrent=false){this.queued=null;this.grab=null;if(this.fold)this.settle(!returnToCurrent&&this.settling&&this.commit,instant);}
 go(direction:1|-1,instant=false){
  if(this.fold&&!instant){this.queued=direction;return;}
  // Repeated button presses queue; grabs can still interrupt immediately.
  this.cancel();const destination=this.spread+direction;if(destination<0||destination>=this.spreads)return;
  if(instant){this.spread=destination;return;}
  this.fold={spread:this.spread,direction,corner:'bottom',point:{x:W-5,y:H-5}};this.velocity={x:-.8,y:-.12};this.settle(true);
 }
 cancel(){this.fold=null;this.grab=null;this.settling=false;this.target=null;this.queued=null;this.velocity={x:0,y:0};}
 advance(dt:number){
  if(!this.settling||!this.fold||!this.target)return;
  dt=Math.min(32,Math.max(1,dt));this.elapsed+=dt;const rate=.023,decay=Math.exp(-rate*dt),old=this.fold.point,next={...old};
  for(const key of ['x','y'] as const){const delta=old[key]-this.target[key],term=(this.velocity[key]+rate*delta)*dt;next[key]=this.target[key]+(delta+term)*decay;this.velocity[key]=(this.velocity[key]-rate*term)*decay;}
  const clamped=clampFold(next,this.fold.corner);if(clamped)this.fold={...this.fold,point:clamped};
  if(Math.hypot(next.x-this.target.x,next.y-this.target.y)<.7&&Math.hypot(this.velocity.x,this.velocity.y)<.035||this.elapsed>650)this.finish();
 }
 private finish(){const queued=this.queued;if(this.fold&&this.commit)this.spread=Math.max(0,Math.min(this.spreads-1,this.spread+this.fold.direction));this.cancel();if(queued)this.go(queued);}
}
