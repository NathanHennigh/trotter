import { dreamMarkerImages } from '../../../assets/generated/dreamMarkerManifest';
import { placeSymbol } from './placeSymbols';
import type { PlaceCluster } from './dreamMapModel';

export function dreamMarkerImage(cluster: PlaceCluster, selected: boolean) {
  const count = cluster.points.length;
  const key = count > 1 ? count > 99 ? 'count-99plus' : `count-${count}`
    : cluster.points[0].area ? 'area' : placeSymbol(cluster.points[0].category ?? 'unknown');
  return dreamMarkerImages[key][selected ? 1 : 0];
}
