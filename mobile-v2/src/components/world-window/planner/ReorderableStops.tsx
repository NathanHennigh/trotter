import React from 'react';
import { Animated, PanResponder, StyleSheet, View, type GestureResponderHandlers } from 'react-native';
import type { PlannerStop } from '../../../services/planner';
import { colors } from '../../../theme/trotterTheme';
import { selectionHaptic } from '../../../utils/experiencePreferences';
import { paperEase, useReducedMotion } from '../motion';
import { reorderPreview, reorderTarget, stopPositions } from './itineraryNavigation';

type Handle = GestureResponderHandlers & { onMoveEarlier: () => void; onMoveLater: () => void };
export function ReorderableStops({ stops, enabled, onReorder, onDragging, renderStop }: {
  stops: PlannerStop[]; enabled: boolean; onReorder: (id: string, offset: number) => boolean;
  onDragging: (value: boolean) => void; renderStop: (stop: PlannerStop, handle?: Handle) => React.ReactNode;
}) {
  const [heights, setHeights] = React.useState<Record<string, number>>({});
  const [drag, setDrag] = React.useState<{ id: string; target: number; y: number }>();
  const active = React.useRef<{ id: string; start: number; target: number; y: number } | undefined>(undefined);
  const ids = stops.map(stop => stop.id), original = stopPositions(ids, heights);
  const order = drag ? reorderPreview(ids, drag.id, drag.target) : ids, preview = stopPositions(order, heights);
  const current = React.useRef({ ids, heights, enabled, onReorder, onDragging }); current.current = { ids, heights, enabled, onReorder, onDragging };
  const reduced = useReducedMotion();
  const cancel = React.useCallback(() => { active.current = undefined; setDrag(undefined); current.current.onDragging(false); }, []);
  React.useEffect(() => { if (!enabled && active.current) cancel(); }, [enabled, cancel]);
  React.useEffect(() => () => { current.current.onDragging(false); }, []);
  const begin = (id: string) => {
    if (!current.current.enabled || active.current) return;
    const { ids, heights } = current.current, target = ids.indexOf(id), start = stopPositions(ids, heights).positions[id];
    active.current = { id, start, target, y: start }; setDrag({ id, target, y: start }); onDragging(true); selectionHaptic();
  };
  const move = (dy: number) => {
    const item = active.current; if (!item) return;
    const { ids, heights } = current.current, total = stopPositions(ids, heights).height;
    item.y = Math.max(0, Math.min(total - (heights[item.id] || 94), item.start + dy));
    item.target = reorderTarget(ids, item.id, item.y - item.start, heights);
    setDrag({ id: item.id, target: item.target, y: item.y });
  };
  const finish = () => {
    const item = active.current; if (!item) return;
    if (!current.current.enabled) { cancel(); return; }
    const offset = item.target - current.current.ids.indexOf(item.id);
    // The caller applies the optimistic order synchronously. Positions settle into that
    // order immediately; a failed request later animates back to the authoritative plan.
    active.current = undefined;
    if (offset) current.current.onReorder(item.id, offset);
    setDrag(undefined); current.current.onDragging(false);
  };
  return <View style={{ height: preview.height }}>
    {stops.map(stop => <MovableStop key={stop.id} y={drag?.id === stop.id ? drag.y : preview.positions[stop.id]} initialY={original.positions[stop.id]}
      dragging={drag?.id === stop.id} enabled={enabled && !stop.locked} reduced={reduced}
      onMeasure={height => setHeights(value => value[stop.id] === height ? value : { ...value, [stop.id]: height })}
      onBegin={() => begin(stop.id)} onMove={move} onFinish={finish} onCancel={cancel}
      onMoveEarlier={() => enabled && onReorder(stop.id, -1)} onMoveLater={() => enabled && onReorder(stop.id, 1)}
      render={handle => renderStop(stop, stop.locked ? undefined : handle)} />)}
  </View>;
}

function MovableStop({ y, initialY, dragging, enabled, reduced, onMeasure, onBegin, onMove, onFinish, onCancel, onMoveEarlier, onMoveLater, render }: {
  y: number; initialY: number; dragging: boolean; enabled: boolean; reduced: boolean; onMeasure: (height: number) => void;
  onBegin: () => void; onMove: (dy: number) => void; onFinish: () => void; onCancel: () => void;
  onMoveEarlier: () => void; onMoveLater: () => void; render: (handle: Handle) => React.ReactNode;
}) {
  const translation = React.useRef(new Animated.Value(initialY)).current;
  const latest = React.useRef({ enabled, onBegin, onMove, onFinish, onCancel }); latest.current = { enabled, onBegin, onMove, onFinish, onCancel };
  const responder = React.useMemo(() => PanResponder.create({
    onStartShouldSetPanResponder: () => latest.current.enabled,
    onMoveShouldSetPanResponder: (_, gesture) => latest.current.enabled && Math.abs(gesture.dy) > 4,
    onPanResponderGrant: () => latest.current.onBegin(), onPanResponderMove: (_, gesture) => latest.current.onMove(gesture.dy),
    onPanResponderRelease: () => latest.current.onFinish(), onPanResponderTerminate: () => latest.current.onCancel(),
    onPanResponderTerminationRequest: () => false,
  }), []);
  React.useLayoutEffect(() => {
    translation.stopAnimation();
    if (dragging || reduced) translation.setValue(y);
    else Animated.timing(translation, { toValue: y, duration: 180, easing: paperEase, useNativeDriver: true }).start();
  }, [y, dragging, reduced, translation]);
  React.useEffect(() => () => translation.stopAnimation(), [translation]);
  return <Animated.View onLayout={event => onMeasure(event.nativeEvent.layout.height)}
    style={[styles.row, { transform: [{ translateY: translation }], zIndex: dragging ? 2 : 0 }, dragging && styles.lifted]}>
    {render({ ...responder.panHandlers, onMoveEarlier, onMoveLater })}
  </Animated.View>;
}

const styles = StyleSheet.create({
  row: { position: 'absolute', left: 0, right: 0, top: 0, backgroundColor: colors.paperSoft },
  lifted: { backgroundColor: colors.paperPhoto, shadowColor: colors.ink, shadowOpacity: 0.10, shadowRadius: 8, elevation: 4 },
});
