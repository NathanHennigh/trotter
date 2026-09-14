export const passportMaterials={
 lounge:{cover:'#284d3a',edge:'#183b2a',paper:'#f8f0dd',paperEdge:'#d8ccb1',ink:'#415542',foil:'#e2cf9b',gutter:'78,67,41'},
 window:{cover:'#294e65',edge:'#17384d',paper:'#f5f2e9',paperEdge:'#d4d2c7',ink:'#3e5960',foil:'#d5e2e8',gutter:'47,67,77'},
} as const;
export function passportMaterial(variant:string){return variant==='window'?passportMaterials.window:passportMaterials.lounge;}
