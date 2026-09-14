/** Geometry-only StPageFlip 2.0.7; Copyright (c) 2020 Nodlik, MIT. */
type FoldPoint = { x: number; y: number };
type FoldRect = { topLeft: FoldPoint; topRight: FoldPoint; bottomLeft: FoldPoint; bottomRight: FoldPoint };
type FoldDirection = 0 | 1;
type FoldCorner = "top" | "bottom";
/** Call calc() successfully before reading geometry. Ignore failed/degenerate samples. */
export declare class FlipCalculation {
  constructor(direction: FoldDirection, corner: FoldCorner, pageWidth: string, pageHeight: string);
  calc(localPos: FoldPoint): boolean;
  getFlippingClipArea(): (FoldPoint | null)[];
  getBottomClipArea(): (FoldPoint | null)[];
  getAngle(): number;
  getRect(): FoldRect;
  getPosition(): FoldPoint;
  getActiveCorner(): FoldPoint;
  getDirection(): FoldDirection;
  getFlippingProgress(): number;
  getCorner(): FoldCorner;
  getBottomPagePosition(): FoldPoint;
  getShadowStartPoint(): FoldPoint | null;
  /** May be undefined geometrically at a perfectly flat fold; guard finite output. */
  getShadowAngle(): number;
}
