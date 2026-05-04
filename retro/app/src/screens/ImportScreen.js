import React, { useEffect, useRef, useState } from 'react';
import {
  View, Text, TouchableOpacity, StyleSheet, Animated, Easing,
} from 'react-native';
import { useAuthStore }    from '../store/useAuthStore';
import { useFlightsStore } from '../store/useFlightsStore';
import { startImport, pollJob } from '../api/ingest';

const POLL_MS = 2000;

function FlipNumber({ value, style }) {
  return (
    <View style={ss.flipWrap}>
      <Text style={[ss.flipNum, style]}>{String(value).padStart(5, '0')}</Text>
    </View>
  );
}

function CassetteSpinner({ running }) {
  const spin = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    if (!running) { spin.setValue(0); return; }
    Animated.loop(Animated.timing(spin, { toValue: 1, duration: 900, easing: Easing.linear, useNativeDriver: true })).start();
  }, [running]);
  const rotate = spin.interpolate({ inputRange: [0, 1], outputRange: ['0deg', '360deg'] });
  return (
    <View style={ss.cassetteWrap}>
      <View style={ss.cassetteLed} />
      <View style={{ flexDirection: 'row', gap: 24, alignItems: 'center', justifyContent: 'center' }}>
        {[1, 2].map(i => (
          <Animated.View key={i} style={{ transform: [{ rotate }] }}>
            <View style={ss.spool}><View style={ss.spoolHub} /></View>
          </Animated.View>
        ))}
      </View>
      <Text style={ss.cassetteStatus}>{running ? 'READ' : 'IDLE'}</Text>
    </View>
  );
}

export default function ImportScreen({ onDone, onBack }) {
  const token   = useAuthStore(s => s.token);
  const loadFlights = useFlightsStore(s => s.load);

  const [jobId,    setJobId]    = useState(null);
  const [state,    setState]    = useState('idle'); // idle|running|completed|failed
  const [scanned,  setScanned]  = useState(0);
  const [parsed,   setParsed]   = useState(0);
  const [segments, setSegments] = useState(0);
  const [lastLine, setLastLine] = useState('AWAITING COMMAND...');
  const [errMsg,   setErrMsg]   = useState(null);
  const pollRef = useRef(null);

  const stopPolling = () => { if (pollRef.current) clearInterval(pollRef.current); };

  const handleStart = async () => {
    setState('running');
    setLastLine('INITIATING GMAIL SCAN...');
    try {
      const { job_id } = await startImport(token);
      setJobId(job_id);
      setLastLine(`JOB ${job_id.slice(0, 8)}... QUEUED`);

      pollRef.current = setInterval(async () => {
        try {
          const job = await pollJob(token, job_id);
          setScanned(job.scanned_count);
          setParsed(job.parsed_count);
          setSegments(job.segment_count);
          setLastLine(`SCANNED ${job.scanned_count} | FOUND ${job.parsed_count} FLIGHTS`);

          if (job.state === 'completed') {
            stopPolling();
            setState('completed');
            setLastLine('SYNC COMPLETE. LOADING MANIFEST...');
            await loadFlights(token);
            setTimeout(onDone, 1500);
          } else if (job.state === 'failed') {
            stopPolling();
            setState('failed');
            setErrMsg(job.error_message ?? 'Unknown error');
            setLastLine('! ACQUISITION FAILED');
          }
        } catch (e) {
          setLastLine(`WARN: ${e.message}`);
        }
      }, POLL_MS);
    } catch (e) {
      setState('failed');
      setErrMsg(e.message);
      setLastLine('! FAILED TO START JOB');
    }
  };

  useEffect(() => () => stopPolling(), []);

  const running    = state === 'running';
  const completed  = state === 'completed';
  const failed     = state === 'failed';
  const idle       = state === 'idle';
  const GREEN      = '#6ab04c';
  const AMBER      = '#ff9500';
  const RED        = '#e8006f';

  return (
    <View style={ss.container}>
      {/* Header */}
      <View style={ss.header}>
        <Text style={ss.headerTitle}>DATA ACQUISITION</Text>
        <TouchableOpacity onPress={onBack}>
          <Text style={ss.backBtn}>← HOME</Text>
        </TouchableOpacity>
      </View>

      {/* CRT body */}
      <View style={ss.crt}>
        {/* Cassette */}
        <CassetteSpinner running={running} />

        {/* Live counters */}
        <View style={ss.counters}>
          {[
            { label: 'SCANNED', value: scanned, color: AMBER },
            { label: 'FLIGHTS', value: parsed,  color: GREEN },
            { label: 'SEGMENTS',value: segments,color: GREEN },
          ].map(({ label, value, color }) => (
            <View key={label} style={ss.counterCell}>
              <Text style={[ss.counterLabel, { color: '#2d5a1b' }]}>{label}</Text>
              <FlipNumber value={value} style={{ color }} />
            </View>
          ))}
        </View>

        {/* Progress bar — based on scanned (capped at 2000 for display) */}
        <View style={ss.progressTrack}>
          <View style={[ss.progressFill, {
            width: `${Math.min(100, (scanned / 2000) * 100)}%`,
            backgroundColor: completed ? GREEN : running ? AMBER : '#1a1a1a',
          }]} />
        </View>

        {/* Live status line */}
        <Text style={[ss.lastLine, failed && { color: RED }]}>{lastLine}</Text>
        {failed && errMsg && <Text style={[ss.lastLine, { color: RED, fontSize: 9 }]}>{errMsg}</Text>}

        {/* Receipt window - latest find */}
        {segments > 0 && (
          <View style={ss.receipt}>
            <View style={ss.receiptHdr}>
              <Text style={ss.receiptHdrTxt}>LATEST ACQUISITION</Text>
            </View>
            <View style={ss.receiptBody}>
              <Text style={ss.receiptStat}>{segments} SEGMENTS LOGGED</Text>
              <Text style={ss.receiptStat}>{parsed} EMAILS MATCHED</Text>
            </View>
          </View>
        )}
      </View>

      {/* Control panel */}
      <View style={ss.panel}>
        {idle && (
          <TouchableOpacity style={ss.startBtn} onPress={handleStart} activeOpacity={0.85}>
            <Text style={ss.startBtnTxt}>▶  BEGIN ACQUISITION</Text>
          </TouchableOpacity>
        )}
        {failed && (
          <View style={{ flexDirection: 'row', gap: 10 }}>
            <TouchableOpacity style={[ss.startBtn, { flex: 1 }]} onPress={handleStart} activeOpacity={0.85}>
              <Text style={ss.startBtnTxt}>↺  RETRY</Text>
            </TouchableOpacity>
            <TouchableOpacity style={[ss.startBtn, ss.secBtn, { flex: 1 }]} onPress={onBack} activeOpacity={0.85}>
              <Text style={[ss.startBtnTxt, { color: '#ccc5a0' }]}>← BACK</Text>
            </TouchableOpacity>
          </View>
        )}
        {(running || completed) && (
          <View style={[ss.startBtn, { opacity: 0.4 }]}>
            <Text style={ss.startBtnTxt}>{completed ? '✓ COMPLETE' : '● RUNNING...'}</Text>
          </View>
        )}
      </View>
    </View>
  );
}

const ss = StyleSheet.create({
  container:   { flex: 1, backgroundColor: '#d4c8a8' },
  header:      {
    backgroundColor: '#1a1a1a', paddingTop: 52, paddingHorizontal: 20, paddingBottom: 14,
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 1, shadowRadius: 0, elevation: 8,
  },
  headerTitle: { fontFamily: 'SpaceMono', fontSize: 11, fontWeight: '900', letterSpacing: 4, color: '#ccc5a0' },
  backBtn:     { fontFamily: 'SpaceMono', fontSize: 9, color: '#e8006f', letterSpacing: 2 },
  crt: {
    flex: 1, backgroundColor: '#050c03', padding: 20,
    justifyContent: 'center', alignItems: 'center', gap: 18,
  },
  cassetteWrap: {
    width: 140, height: 80, backgroundColor: '#08080a',
    borderRadius: 8, borderWidth: 2, borderColor: '#050506',
    alignItems: 'center', justifyContent: 'center', gap: 4,
  },
  cassetteLed: { position: 'absolute', top: 6, right: 8, width: 6, height: 6, borderRadius: 3, backgroundColor: '#ff2020', shadowColor: '#ff2020', shadowOpacity: 1, shadowRadius: 6 },
  spool:        { width: 24, height: 24, borderRadius: 12, backgroundColor: '#141410', borderWidth: 1, borderColor: '#2a2a20', alignItems: 'center', justifyContent: 'center' },
  spoolHub:     { width: 8, height: 8, borderRadius: 4, backgroundColor: '#0a0a08' },
  cassetteStatus: { fontFamily: 'SpaceMono', fontSize: 7, letterSpacing: 3, color: 'rgba(80,70,40,0.5)', textTransform: 'uppercase' },
  counters:     { flexDirection: 'row', gap: 16, justifyContent: 'center' },
  counterCell:  { alignItems: 'center', gap: 3 },
  counterLabel: { fontFamily: 'SpaceMono', fontSize: 7, fontWeight: '900', letterSpacing: 2, textTransform: 'uppercase' },
  flipWrap:     { backgroundColor: '#0a1205', borderRadius: 3, paddingHorizontal: 6, paddingVertical: 3, borderWidth: 1, borderColor: '#1a3010' },
  flipNum:      { fontFamily: 'SpaceMono', fontSize: 18, letterSpacing: 2 },
  progressTrack:{ width: '100%', height: 10, backgroundColor: '#0f1f08', borderRadius: 3, borderWidth: 1, borderColor: '#2d5a1b', overflow: 'hidden' },
  progressFill: { height: '100%', borderRadius: 2 },
  lastLine:     { fontFamily: 'SpaceMono', fontSize: 9, color: '#4a7c2f', letterSpacing: 2, textAlign: 'center' },
  receipt: { width: '100%', backgroundColor: '#f5f0e0', borderRadius: 3, overflow: 'hidden' },
  receiptHdr:   { backgroundColor: '#1a1a1a', paddingVertical: 4, paddingHorizontal: 10 },
  receiptHdrTxt:{ fontFamily: 'SpaceMono', fontSize: 8, fontWeight: '900', letterSpacing: 3, color: '#ccc5a0' },
  receiptBody:  { padding: 8, gap: 2 },
  receiptStat:  { fontFamily: 'SpaceMono', fontSize: 10, color: '#3a3020' },
  panel:        { padding: 16, paddingBottom: 32, backgroundColor: '#d4c8a8' },
  startBtn: {
    backgroundColor: '#e8006f', paddingVertical: 14, borderRadius: 6, alignItems: 'center',
    shadowColor: '#8a0040', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 1, shadowRadius: 0, elevation: 6,
  },
  secBtn:      { backgroundColor: '#1a1a1a', shadowColor: '#000' },
  startBtnTxt: { fontFamily: 'SpaceMono', fontSize: 11, fontWeight: '900', letterSpacing: 3, color: '#fff' },
});
