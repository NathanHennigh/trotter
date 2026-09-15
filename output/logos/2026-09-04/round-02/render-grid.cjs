const fs = require('node:fs');
const path = require('node:path');
const {createCanvas, loadImage} = require('@napi-rs/canvas');
const sharp = require('sharp');
const root = 'C:/Users/natha/projects/trotter/output/logos/2026-09-04/round-02';
const tiles = [["06","Sunrise stride","06-sunrise-stride.png"],["10","Traveling T","10-traveling-t.png"],["11","Winged foot","11-winged-foot.png"],["12","Globe trot","12-globe-trot.png"],["06A","Lifted stride","06a-lifted-stride.png"],["10A","Compact T","10a-compact-t.png"],["11A","Free flight","11a-free-flight.png"],["12A","Light footed","12a-light-footed.png"],["06B","Sun cut","06b-sun-cut.png"],["10B","Orbit T","10b-orbit-t.png"],["11B","Wing cut","11b-wing-cut.png"],["12B","Meridian stride","12b-meridian-stride.png"],["13","World traveler","13-world-traveler.png"],["14","Winged world","14-winged-world.png"],["15","Flight path T","15-flight-path-t.png"],["16","Sun trot","16-sun-trot.png"]];
(async () => {
  const W=2400,H=2740,margin=80,col=560,row=610,start=180;
  const canvas=createCanvas(W,H),ctx=canvas.getContext('2d');
  ctx.fillStyle='#F4EFDF';ctx.fillRect(0,0,W,H);
  ctx.fillStyle='#183F43';ctx.font='76px Georgia';ctx.fillText('Trotter',margin,108);
  ctx.font='23px Arial';ctx.textAlign='right';ctx.fillText('LOGO EXPLORATIONS  /  ROUND 02',W-margin,102);ctx.textAlign='left';
  ctx.strokeStyle='#183F43';ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(margin,144);ctx.lineTo(W-margin,144);ctx.stroke();
  const imgs=await Promise.all(tiles.map(t=>loadImage(path.join(root,t[2]))));
  for(let i=0;i<16;i++){
    const c=i%4,r=Math.floor(i/4),x=margin+c*col,y=start+r*row;
    ctx.drawImage(imgs[i],x+22,y+12,516,516);
    ctx.fillStyle='#817354';ctx.font='bold 22px Arial';ctx.fillText(tiles[i][0],x+25,y+573);
    ctx.fillStyle='#183F43';ctx.font='27px Arial';ctx.fillText(tiles[i][1],x+101,y+573);
  }
  ctx.strokeStyle='#D8D6C7';ctx.lineWidth=1.4;
  for(let c=1;c<4;c++){ctx.beginPath();ctx.moveTo(margin+c*col,start);ctx.lineTo(margin+c*col,start+4*row);ctx.stroke();}
  for(let r=1;r<4;r++){ctx.beginPath();ctx.moveTo(margin,start+r*row);ctx.lineTo(W-margin,start+r*row);ctx.stroke();}
  ctx.strokeStyle='#183F43';ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(margin,2640);ctx.lineTo(W-margin,2640);ctx.stroke();
  ctx.fillStyle='#68736C';ctx.font='23px Arial';ctx.fillText('TOP: FAVORITES     /     MIDDLE: VARIATIONS     /     BOTTOM: NEW IDEAS',margin,2690);
  ctx.textAlign='right';ctx.fillText('16 CONCEPTS',W-margin,2690);
  const png=canvas.toBuffer('image/png');
  const stem=path.join(root,'trotter-logo-grid-round-02');
  fs.writeFileSync(stem+'.png',png);
  await sharp(png).jpeg({quality:94,chromaSubsampling:'4:4:4'}).toFile(stem+'.jpg');
  console.log(JSON.stringify({width:W,height:H,logos:tiles.length,png:stem+'.png',jpg:stem+'.jpg',pngBytes:fs.statSync(stem+'.png').size,jpgBytes:fs.statSync(stem+'.jpg').size}));
})();
