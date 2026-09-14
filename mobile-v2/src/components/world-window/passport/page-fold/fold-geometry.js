/**
 * Geometry only, derived from StPageFlip / page-flip 2.0.7.
 * Copyright (c) 2020 Nodlik. Distributed under the MIT License; see LICENSE.
 * Sources: src/Helper.ts and src/Flip/FlipCalculation.ts.
 * Adaptation: imports removed, enums inlined, Helper made private to this module,
 * TypeScript transpiled to ES2020. The calculation algorithm is unchanged.
 * https://github.com/Nodlik/StPageFlip
 */
const FlipCorner = { TOP: 'top', BOTTOM: 'bottom' };
const FlipDirection = { FORWARD: 0, BACK: 1 };
class Helper {
    static GetDistanceBetweenTwoPoint(point1, point2) {
        if (point1 === null || point2 === null) {
            return Infinity;
        }
        return Math.sqrt(Math.pow(point2.x - point1.x, 2) + Math.pow(point2.y - point1.y, 2));
    }
    static GetSegmentLength(segment) {
        return Helper.GetDistanceBetweenTwoPoint(segment[0], segment[1]);
    }
    static GetAngleBetweenTwoLine(line1, line2) {
        const A1 = line1[0].y - line1[1].y;
        const A2 = line2[0].y - line2[1].y;
        const B1 = line1[1].x - line1[0].x;
        const B2 = line2[1].x - line2[0].x;
        return Math.acos((A1 * A2 + B1 * B2) / (Math.sqrt(A1 * A1 + B1 * B1) * Math.sqrt(A2 * A2 + B2 * B2)));
    }
    static PointInRect(rect, pos) {
        if (pos === null) {
            return null;
        }
        if (pos.x >= rect.left &&
            pos.x <= rect.width + rect.left &&
            pos.y >= rect.top &&
            pos.y <= rect.top + rect.height) {
            return pos;
        }
        return null;
    }
    static GetRotatedPoint(transformedPoint, startPoint, angle) {
        return {
            x: transformedPoint.x * Math.cos(angle) + transformedPoint.y * Math.sin(angle) + startPoint.x,
            y: transformedPoint.y * Math.cos(angle) - transformedPoint.x * Math.sin(angle) + startPoint.y,
        };
    }
    static LimitPointToCircle(startPoint, radius, limitedPoint) {
        if (Helper.GetDistanceBetweenTwoPoint(startPoint, limitedPoint) <= radius) {
            return limitedPoint;
        }
        const a = startPoint.x;
        const b = startPoint.y;
        const n = limitedPoint.x;
        const m = limitedPoint.y;
        let x = Math.sqrt((Math.pow(radius, 2) * Math.pow(a - n, 2)) / (Math.pow(a - n, 2) + Math.pow(b - m, 2))) + a;
        if (limitedPoint.x < 0) {
            x *= -1;
        }
        let y = ((x - a) * (b - m)) / (a - n) + b;
        if (a - n + b === 0) {
            y = radius;
        }
        return { x, y };
    }
    static GetIntersectBetweenTwoSegment(rectBorder, one, two) {
        return Helper.PointInRect(rectBorder, Helper.GetIntersectBeetwenTwoLine(one, two));
    }
    static GetIntersectBeetwenTwoLine(one, two) {
        const A1 = one[0].y - one[1].y;
        const A2 = two[0].y - two[1].y;
        const B1 = one[1].x - one[0].x;
        const B2 = two[1].x - two[0].x;
        const C1 = one[0].x * one[1].y - one[1].x * one[0].y;
        const C2 = two[0].x * two[1].y - two[1].x * two[0].y;
        const det1 = A1 * C2 - A2 * C1;
        const det2 = B1 * C2 - B2 * C1;
        const x = -((C1 * B2 - C2 * B1) / (A1 * B2 - A2 * B1));
        const y = -((A1 * C2 - A2 * C1) / (A1 * B2 - A2 * B1));
        if (isFinite(x) && isFinite(y)) {
            return { x, y };
        }
        else {
            if (Math.abs(det1 - det2) < 0.1)
                throw new Error('Segment included');
        }
        return null;
    }
    static GetCordsFromTwoPoint(pointOne, pointTwo) {
        const sizeX = Math.abs(pointOne.x - pointTwo.x);
        const sizeY = Math.abs(pointOne.y - pointTwo.y);
        const lengthLine = Math.max(sizeX, sizeY);
        const result = [pointOne];
        function getCord(c1, c2, size, length, index) {
            if (c2 > c1) {
                return c1 + index * (size / length);
            }
            else if (c2 < c1) {
                return c1 - index * (size / length);
            }
            return c1;
        }
        for (let i = 1; i <= lengthLine; i += 1) {
            result.push({
                x: getCord(pointOne.x, pointTwo.x, sizeX, lengthLine, i),
                y: getCord(pointOne.y, pointTwo.y, sizeY, lengthLine, i),
            });
        }
        return result;
    }
}
export class FlipCalculation {
    constructor(direction, corner, pageWidth, pageHeight) {
        this.direction = direction;
        this.corner = corner;
        this.topIntersectPoint = null;
        this.sideIntersectPoint = null;
        this.bottomIntersectPoint = null;
        this.pageWidth = parseInt(pageWidth, 10);
        this.pageHeight = parseInt(pageHeight, 10);
    }
    calc(localPos) {
        try {
            this.position = this.calcAngleAndPosition(localPos);
            this.calculateIntersectPoint(this.position);
            return true;
        }
        catch (e) {
            return false;
        }
    }
    getFlippingClipArea() {
        const result = [];
        let clipBottom = false;
        result.push(this.rect.topLeft);
        result.push(this.topIntersectPoint);
        if (this.sideIntersectPoint === null) {
            clipBottom = true;
        }
        else {
            result.push(this.sideIntersectPoint);
            if (this.bottomIntersectPoint === null)
                clipBottom = false;
        }
        result.push(this.bottomIntersectPoint);
        if (clipBottom || this.corner === FlipCorner.BOTTOM) {
            result.push(this.rect.bottomLeft);
        }
        return result;
    }
    getBottomClipArea() {
        const result = [];
        result.push(this.topIntersectPoint);
        if (this.corner === FlipCorner.TOP) {
            result.push({ x: this.pageWidth, y: 0 });
        }
        else {
            if (this.topIntersectPoint !== null) {
                result.push({ x: this.pageWidth, y: 0 });
            }
            result.push({ x: this.pageWidth, y: this.pageHeight });
        }
        if (this.sideIntersectPoint !== null) {
            if (Helper.GetDistanceBetweenTwoPoint(this.sideIntersectPoint, this.topIntersectPoint) >= 10)
                result.push(this.sideIntersectPoint);
        }
        else {
            if (this.corner === FlipCorner.TOP) {
                result.push({ x: this.pageWidth, y: this.pageHeight });
            }
        }
        result.push(this.bottomIntersectPoint);
        result.push(this.topIntersectPoint);
        return result;
    }
    getAngle() {
        if (this.direction === FlipDirection.FORWARD) {
            return -this.angle;
        }
        return this.angle;
    }
    getRect() {
        return this.rect;
    }
    getPosition() {
        return this.position;
    }
    getActiveCorner() {
        if (this.direction === FlipDirection.FORWARD) {
            return this.rect.topLeft;
        }
        return this.rect.topRight;
    }
    getDirection() {
        return this.direction;
    }
    getFlippingProgress() {
        return Math.abs(((this.position.x - this.pageWidth) / (2 * this.pageWidth)) * 100);
    }
    getCorner() {
        return this.corner;
    }
    getBottomPagePosition() {
        if (this.direction === FlipDirection.BACK) {
            return { x: this.pageWidth, y: 0 };
        }
        return { x: 0, y: 0 };
    }
    getShadowStartPoint() {
        if (this.corner === FlipCorner.TOP) {
            return this.topIntersectPoint;
        }
        else {
            if (this.sideIntersectPoint !== null)
                return this.sideIntersectPoint;
            return this.topIntersectPoint;
        }
    }
    getShadowAngle() {
        const angle = Helper.GetAngleBetweenTwoLine(this.getSegmentToShadowLine(), [
            { x: 0, y: 0 },
            { x: this.pageWidth, y: 0 },
        ]);
        if (this.direction === FlipDirection.FORWARD) {
            return angle;
        }
        return Math.PI - angle;
    }
    calcAngleAndPosition(pos) {
        let result = pos;
        this.updateAngleAndGeometry(result);
        if (this.corner === FlipCorner.TOP) {
            result = this.checkPositionAtCenterLine(result, { x: 0, y: 0 }, { x: 0, y: this.pageHeight });
        }
        else {
            result = this.checkPositionAtCenterLine(result, { x: 0, y: this.pageHeight }, { x: 0, y: 0 });
        }
        if (Math.abs(result.x - this.pageWidth) < 1 && Math.abs(result.y) < 1) {
            throw new Error('Point is too small');
        }
        return result;
    }
    updateAngleAndGeometry(pos) {
        this.angle = this.calculateAngle(pos);
        this.rect = this.getPageRect(pos);
    }
    calculateAngle(pos) {
        const left = this.pageWidth - pos.x + 1;
        const top = this.corner === FlipCorner.BOTTOM ? this.pageHeight - pos.y : pos.y;
        let angle = 2 * Math.acos(left / Math.sqrt(top * top + left * left));
        if (top < 0)
            angle = -angle;
        const da = Math.PI - angle;
        if (!isFinite(angle) || (da >= 0 && da < 0.003))
            throw new Error('The G point is too small');
        if (this.corner === FlipCorner.BOTTOM)
            angle = -angle;
        return angle;
    }
    getPageRect(localPos) {
        if (this.corner === FlipCorner.TOP) {
            return this.getRectFromBasePoint([
                { x: 0, y: 0 },
                { x: this.pageWidth, y: 0 },
                { x: 0, y: this.pageHeight },
                { x: this.pageWidth, y: this.pageHeight },
            ], localPos);
        }
        return this.getRectFromBasePoint([
            { x: 0, y: -this.pageHeight },
            { x: this.pageWidth, y: -this.pageHeight },
            { x: 0, y: 0 },
            { x: this.pageWidth, y: 0 },
        ], localPos);
    }
    getRectFromBasePoint(points, localPos) {
        return {
            topLeft: this.getRotatedPoint(points[0], localPos),
            topRight: this.getRotatedPoint(points[1], localPos),
            bottomLeft: this.getRotatedPoint(points[2], localPos),
            bottomRight: this.getRotatedPoint(points[3], localPos),
        };
    }
    getRotatedPoint(transformedPoint, startPoint) {
        return {
            x: transformedPoint.x * Math.cos(this.angle) +
                transformedPoint.y * Math.sin(this.angle) +
                startPoint.x,
            y: transformedPoint.y * Math.cos(this.angle) -
                transformedPoint.x * Math.sin(this.angle) +
                startPoint.y,
        };
    }
    calculateIntersectPoint(pos) {
        const boundRect = {
            left: -1,
            top: -1,
            width: this.pageWidth + 2,
            height: this.pageHeight + 2,
        };
        if (this.corner === FlipCorner.TOP) {
            this.topIntersectPoint = Helper.GetIntersectBetweenTwoSegment(boundRect, [pos, this.rect.topRight], [
                { x: 0, y: 0 },
                { x: this.pageWidth, y: 0 },
            ]);
            this.sideIntersectPoint = Helper.GetIntersectBetweenTwoSegment(boundRect, [pos, this.rect.bottomLeft], [
                { x: this.pageWidth, y: 0 },
                { x: this.pageWidth, y: this.pageHeight },
            ]);
            this.bottomIntersectPoint = Helper.GetIntersectBetweenTwoSegment(boundRect, [this.rect.bottomLeft, this.rect.bottomRight], [
                { x: 0, y: this.pageHeight },
                { x: this.pageWidth, y: this.pageHeight },
            ]);
        }
        else {
            this.topIntersectPoint = Helper.GetIntersectBetweenTwoSegment(boundRect, [this.rect.topLeft, this.rect.topRight], [
                { x: 0, y: 0 },
                { x: this.pageWidth, y: 0 },
            ]);
            this.sideIntersectPoint = Helper.GetIntersectBetweenTwoSegment(boundRect, [pos, this.rect.topLeft], [
                { x: this.pageWidth, y: 0 },
                { x: this.pageWidth, y: this.pageHeight },
            ]);
            this.bottomIntersectPoint = Helper.GetIntersectBetweenTwoSegment(boundRect, [this.rect.bottomLeft, this.rect.bottomRight], [
                { x: 0, y: this.pageHeight },
                { x: this.pageWidth, y: this.pageHeight },
            ]);
        }
    }
    checkPositionAtCenterLine(checkedPos, centerOne, centerTwo) {
        let result = checkedPos;
        const tmp = Helper.LimitPointToCircle(centerOne, this.pageWidth, result);
        if (result !== tmp) {
            result = tmp;
            this.updateAngleAndGeometry(result);
        }
        const rad = Math.sqrt(Math.pow(this.pageWidth, 2) + Math.pow(this.pageHeight, 2));
        let checkPointOne = this.rect.bottomRight;
        let checkPointTwo = this.rect.topLeft;
        if (this.corner === FlipCorner.BOTTOM) {
            checkPointOne = this.rect.topRight;
            checkPointTwo = this.rect.bottomLeft;
        }
        if (checkPointOne.x <= 0) {
            const bottomPoint = Helper.LimitPointToCircle(centerTwo, rad, checkPointTwo);
            if (bottomPoint !== result) {
                result = bottomPoint;
                this.updateAngleAndGeometry(result);
            }
        }
        return result;
    }
    getSegmentToShadowLine() {
        const first = this.getShadowStartPoint();
        const second = first !== this.sideIntersectPoint && this.sideIntersectPoint !== null
            ? this.sideIntersectPoint
            : this.bottomIntersectPoint;
        return [first, second];
    }
}
