import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable, Share, TextInput } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { PngStamp, StampShapeKey, StampTemplateBundle, StampTemplate, mergeBox } from '../components/trotter/stamps/PngStamp';
import stampTemplateBundles from '../components/trotter/stamps/stampTemplates.json';
import { colors, fonts, radii, spacing } from '../theme/trotterTheme';

const INITIAL_COUNTRIES = [
  { name: 'USA', label: 'USA (3)', icon: 'united_states_golden_gate_bridge' as const, date: '2022-04-10' },
  { name: 'PERU', label: 'PERU (4)', icon: 'peru_machu_picchu' as const, date: '2023-08-15' },
  { name: 'JAPAN', label: 'JAPAN (5)', icon: 'japan_mount_fuji' as const, date: '2024-05-12' },
  { name: 'FRANCE', label: 'FRANCE (6)', icon: 'france_eiffel_tower' as const, date: '2021-11-20' },
  { name: 'GERMANY', label: 'GERMANY (7)', icon: 'germany_brandenburg_gate' as const, date: '2019-07-04' },
  { name: 'COLOMBIA', label: 'COLOMBIA (8)', icon: 'colombia_cartagena_clock_tower' as const, date: '2020-02-14' },
  { name: 'ARGENTINA', label: 'ARGENTINA (9)', icon: 'argentina_obelisco_de_buenos_aires' as const, date: '2025-01-01' },
  { name: 'SWITZERLAND', label: 'SWITZERLAND (11)', icon: 'switzerland_matterhorn' as const, date: '2018-09-30' },
  { name: 'UNITED KINGDOM', label: 'UNITED KINGDOM (14)', icon: 'united_kingdom_big_ben' as const, date: '2022-12-25' },
  { name: 'DOMINICAN REPUBLIC', label: 'DOMINICAN REP. (18)', icon: 'dominican_republic_puerta_del_conde' as const, date: '2024-03-17' },
];

const ALL_COUNTRIES = [
  'MEXICO', 'CANADA', 'BRAZIL', 'CHILE', 'SPAIN', 'ITALY', 'GREECE', 'EGYPT', 'SOUTH AFRICA', 'KENYA',
  'INDIA', 'CHINA', 'THAILAND', 'VIETNAM', 'AUSTRALIA', 'NEW ZEALAND', 'FIJI', 'ICELAND', 'NORWAY', 'SWEDEN',
  'FINLAND', 'RUSSIA', 'TURKEY', 'MOROCCO', 'NIGERIA', 'MADAGASCAR', 'INDONESIA', 'PHILIPPINES', 'MALAYSIA', 'SINGAPORE',
  'SOUTH KOREA', 'TAIWAN', 'IRELAND', 'PORTUGAL', 'NETHERLANDS', 'BELGIUM', 'AUSTRIA', 'POLAND', 'UKRAINE', 'ROMANIA',
  'HUNGARY', 'CROATIA', 'SERBIA', 'BULGARIA', 'GEORGIA', 'ARMENIA', 'AZERBAIJAN', 'KAZAKHSTAN',
  'UZBEKISTAN', 'AFGHANISTAN', 'PAKISTAN', 'BANGLADESH', 'SRI LANKA', 'NEPAL', 'MYANMAR', 'CAMBODIA', 'LAOS', 'MONGOLIA',
  'SAUDI ARABIA', 'UNITED ARAB EMIRATES', 'OMAN', 'YEMEN', 'JORDAN', 'ISRAEL', 'LEBANON', 'SYRIA', 'IRAQ', 'IRAN',
  'CUBA', 'JAMAICA', 'HAITI', 'BAHAMAS', 'PANAMA', 'COSTA RICA', 'NICARAGUA', 'HONDURAS', 'EL SALVADOR', 'GUATEMALA',
  'VENEZUELA', 'ECUADOR', 'BOLIVIA', 'PARAGUAY', 'URUGUAY', 'GUYANA', 'SURINAME', 'SENEGAL', 'GHANA', 'ETHIOPIA',
  'TANZANIA', 'UGANDA', 'ZAMBIA', 'ZIMBABWE', 'BOTSWANA', 'NAMIBIA', 'ANGOLA', 'MOZAMBIQUE', 'MALAWI', 'RWANDA',
  'BURUNDI', 'SOMALIA', 'DJIBOUTI', 'ERITREA', 'SUDAN', 'CHAD', 'NIGER', 'MALI', 'MAURITANIA', 'MOROCCO'
];

const SHAPES: StampShapeKey[] = [
  'archedCountryCanonical',
  'archedCountryBanner',
  'archedCountryVariant',
  'circularCityClean',
  'circularCityDoubleLine',
  'roundedImmigrationCanonical',
  'roundedImmigrationWithBand',
  'shieldBadgeRounded',
];

const TABS = ['country', 'icon', 'place', 'date', 'airport', 'global'] as const;

function StepperInput({ value, onChange }: { value: string, onChange: (val: number) => void }) {
  const [text, setText] = useState(value);

  useEffect(() => {
    setText(value);
  }, [value]);

  return (
    <TextInput
      style={styles.stepperValue}
      value={text}
      keyboardType="numeric"
      onChangeText={setText}
      onBlur={() => {
        const parsed = parseFloat(text);
        if (!isNaN(parsed)) onChange(parsed);
        else setText(value);
      }}
      onSubmitEditing={() => {
        const parsed = parseFloat(text);
        if (!isNaN(parsed)) onChange(parsed);
        else setText(value);
      }}
    />
  );
}

export function NativeStampEditorScreen() {
  const [templates, setTemplates] = useState<Record<StampShapeKey, StampTemplateBundle>>(stampTemplateBundles as any);
  const [activeShape, setActiveShape] = useState<StampShapeKey>('archedCountryCanonical');
  const [testCountries, setTestCountries] = useState(INITIAL_COUNTRIES);
  const [activeCountry, setActiveCountry] = useState(INITIAL_COUNTRIES[0].name);
  const [activeTab, setActiveTab] = useState<typeof TABS[number]>('country');
  const [size, setSize] = useState<'md' | 'sm'>('md');
  const [editingTarget, setEditingTarget] = useState<'default' | number | 'new'>('default');
  const [minLen, setMinLen] = useState('3');
  const [maxLen, setMaxLen] = useState('3');

  useEffect(() => {
    const len = activeCountry.length;
    const b = templates[activeShape];
    const matchIndex = b.presets?.findIndex((p: any) => len >= p.charRange[0] && len <= p.charRange[1]);

    if (matchIndex !== undefined && matchIndex !== -1) {
      setEditingTarget(matchIndex);
      setMinLen(String(b.presets![matchIndex].charRange[0]));
      setMaxLen(String(b.presets![matchIndex].charRange[1]));
    } else {
      setEditingTarget('default');
    }
  }, [activeShape, activeCountry, templates]);

  const shuffleCountries = () => {
    const shuffled = [...ALL_COUNTRIES].sort(() => 0.5 - Math.random()).slice(0, 10);
    const newTest = shuffled.map(name => ({
      name,
      label: `${name} (${name.length})`,
      icon: 'united_states_golden_gate_bridge' as const,
      date: '2025-01-01'
    }));
    setTestCountries(newTest);
    setActiveCountry(newTest[0].name);
  };

  const activeCountryObj = testCountries.find(c => c.name === activeCountry) || testCountries[0];
  const bundle = templates[activeShape];
  const isPreset = typeof editingTarget === 'number' && bundle.presets && bundle.presets[editingTarget];
  const activePreset = isPreset ? bundle.presets?.[editingTarget as number] : undefined;
  const activeOverrides = activePreset?.overrides as Record<string, any> | undefined;

  let previewTemplate: StampTemplate;
  if (isPreset) {
    const o = bundle.presets![editingTarget as number].overrides;
    previewTemplate = {
      ...bundle.default,
      ...o,
      frame: mergeBox(bundle.default.frame, o.frame),
      country: mergeBox(bundle.default.country, o.country),
      icon: mergeBox(bundle.default.icon, o.icon),
      place: mergeBox(bundle.default.place, o.place),
      date: mergeBox(bundle.default.date, o.date),
      airport: mergeBox(bundle.default.airport, o.airport),
    };
  } else {
    previewTemplate = bundle.default;
  }

  const getResolvedVal = (box: string, field: string) => {
    if (box === 'global') {
      if (activeOverrides?.[field] !== undefined) {
        return activeOverrides[field];
      }
      return bundle.default[field as keyof typeof bundle.default];
    }
    const defBox = bundle.default[box as keyof typeof bundle.default] as any;
    if (activeOverrides) {
      const overBox = activeOverrides[box];
      if (overBox && overBox[field] !== undefined) return overBox[field];
    }
    return defBox?.[field];
  };

  const updateVal = (box: string, field: string, val: number) => {
    setTemplates(prev => {
      const next = JSON.parse(JSON.stringify(prev));
      const b = next[activeShape];
      if (box === 'global') {
        if (isPreset) {
          b.presets[editingTarget as number].overrides[field] = val;
        } else {
          b.default[field] = val;
        }
      } else {
        if (isPreset) {
          if (!b.presets[editingTarget as number].overrides[box]) b.presets[editingTarget as number].overrides[box] = {};
          b.presets[editingTarget as number].overrides[box][field] = val;
        } else {
          b.default[box][field] = val;
        }
      }
      return next;
    });
  };

  const clearVal = (box: string, field: string) => {
    setTemplates(prev => {
      const next = JSON.parse(JSON.stringify(prev));
      const b = next[activeShape];
      if (box === 'global') {
        if (isPreset) {
          delete b.presets[editingTarget as number].overrides[field];
        } else {
          delete b.default[field];
        }
      } else {
        if (isPreset && b.presets[editingTarget as number].overrides[box]) {
          delete b.presets[editingTarget as number].overrides[box][field];
        } else if (b.default[box]) {
          delete b.default[box][field];
        }
      }
      return next;
    });
  };

  const exportJSON = async () => {
    import('react-native').then(({ Keyboard }) => Keyboard.dismiss());
    setTimeout(async () => {
      try {
        await Share.share({ message: JSON.stringify(templates, null, 2) });
      } catch (error: any) {
        alert(error.message);
      }
    }, 100);
  };

  const createPreset = () => {
    const min = parseInt(minLen, 10);
    const max = parseInt(maxLen, 10);
    if (isNaN(min) || isNaN(max) || min > max) {
      alert("Invalid range");
      return;
    }
    setTemplates(prev => {
      const next = JSON.parse(JSON.stringify(prev));
      const b = next[activeShape];
      if (!b.presets) b.presets = [];
      b.presets.push({ charRange: [min, max], overrides: {} });
      b.presets.sort((a: any, b: any) => a.charRange[0] - b.charRange[0]);
      return next;
    });
    setEditingTarget('default');
  };

  const updatePresetRange = () => {
    if (!isPreset) return;
    const min = parseInt(minLen, 10);
    const max = parseInt(maxLen, 10);
    if (isNaN(min) || isNaN(max) || min > max) {
      alert("Invalid range");
      return;
    }
    setTemplates(prev => {
      const next = JSON.parse(JSON.stringify(prev));
      const b = next[activeShape];
      b.presets[editingTarget as number].charRange = [min, max];
      b.presets.sort((a: any, b: any) => a.charRange[0] - b.charRange[0]);
      return next;
    });
    setEditingTarget('default');
  };

  const deletePreset = () => {
    setTemplates(prev => {
      const next = JSON.parse(JSON.stringify(prev));
      const b = next[activeShape];
      if (b.presets) {
        b.presets.splice(editingTarget as number, 1);
        if (b.presets.length === 0) delete b.presets;
      }
      return next;
    });
    setEditingTarget('default');
  };

  const renderStepper = (label: string, field: string, step = 0.01) => {
    const rawVal = getResolvedVal(activeTab, field);
    const val = typeof rawVal === 'number' ? rawVal : 0;
    const isOverride = typeof activeOverrides?.[activeTab]?.[field] === 'number';

    return (
      <View key={field} style={styles.stepperRow}>
        <Text style={[styles.stepperLabel, isOverride && { color: colors.teal }]}>{label}</Text>
        <Pressable onPress={() => updateVal(activeTab, field, val - step)} style={styles.btn}><Text style={styles.btnText}>-</Text></Pressable>
        {typeof rawVal === 'number' ? (
          <StepperInput value={val.toFixed(3)} onChange={(v) => updateVal(activeTab, field, v)} />
        ) : (
          <Text style={styles.stepperValue}>---</Text>
        )}
        <Pressable onPress={() => updateVal(activeTab, field, val + step)} style={styles.btn}><Text style={styles.btnText}>+</Text></Pressable>
        <Pressable onPress={() => clearVal(activeTab, field)} style={styles.btnClear}><Text style={styles.btnClearText}>X</Text></Pressable>
      </View>
    );
  };

  return (
    <SafeAreaView style={styles.root}>
      <View style={styles.previewContainer}>
        <PngStamp
          shape={activeShape}
          color={colors.ink}
          country={activeCountry}
          city={undefined}
          airportCode="LHR"
          date={activeCountryObj.date}
          icon={activeCountryObj.icon}
          size={size}
          templateOverride={previewTemplate}
        />
      </View>

      <View style={styles.controls}>
        <View style={styles.rowScroller}>
          <ScrollView horizontal showsHorizontalScrollIndicator={false}>
            {SHAPES.map(s => (
              <Pressable key={s} onPress={() => setActiveShape(s)} style={[styles.pill, activeShape === s && styles.pillActive]}>
                <Text style={[styles.pillText, activeShape === s && styles.pillTextActive]}>{s.replace(/[A-Z]/g, m => ` ${m}`).trim()}</Text>
              </Pressable>
            ))}
          </ScrollView>
        </View>

        <View style={styles.rowScroller}>
          <ScrollView horizontal showsHorizontalScrollIndicator={false}>
            <Pressable onPress={shuffleCountries} style={[styles.pill, { backgroundColor: colors.red }]}>
              <Text style={styles.pillText}>🎲 Shuffle</Text>
            </Pressable>
            {testCountries.map(c => (
              <Pressable key={c.name} onPress={() => setActiveCountry(c.name)} style={[styles.pill, activeCountry === c.name && styles.pillActive]}>
                <Text style={[styles.pillText, activeCountry === c.name && styles.pillTextActive]}>{c.label}</Text>
              </Pressable>
            ))}
          </ScrollView>
        </View>

        <View style={styles.rowScroller}>
          <ScrollView horizontal showsHorizontalScrollIndicator={false}>
            <Pressable onPress={() => setEditingTarget('default')} style={[styles.pill, editingTarget === 'default' && styles.pillActive]}>
              <Text style={[styles.pillText, editingTarget === 'default' && styles.pillTextActive]}>Default</Text>
            </Pressable>
            {bundle.presets?.map((p, i) => (
              <Pressable key={i} onPress={() => { setEditingTarget(i); setMinLen(String(p.charRange[0])); setMaxLen(String(p.charRange[1])); }} style={[styles.pill, editingTarget === i && styles.pillActive]}>
                <Text style={[styles.pillText, editingTarget === i && styles.pillTextActive]}>[{p.charRange[0]}-{p.charRange[1]}]</Text>
              </Pressable>
            ))}
            <Pressable onPress={() => { setEditingTarget('new'); setMinLen('3'); setMaxLen('3'); }} style={[styles.pill, editingTarget === 'new' && styles.pillActive]}>
              <Text style={[styles.pillText, editingTarget === 'new' && styles.pillTextActive]}>+ New Preset</Text>
            </Pressable>
          </ScrollView>
        </View>

        <View style={styles.headerRow}>
          {isPreset ? (
            <View style={styles.presetMgmt}>
              <Text style={styles.headerText}>Preset</Text>
              <View style={styles.presetInputs}>
                <TextInput style={styles.input} value={minLen} onChangeText={setMinLen} keyboardType="numeric" />
                <Text style={styles.inputDash}>-</Text>
                <TextInput style={styles.input} value={maxLen} onChangeText={setMaxLen} keyboardType="numeric" />
                <Pressable onPress={updatePresetRange} style={styles.btnCreate}><Text style={styles.btnCreateText}>SAVE</Text></Pressable>
                <Pressable onPress={deletePreset} style={styles.btnDanger}><Text style={styles.btnDangerText}>DEL</Text></Pressable>
              </View>
            </View>
          ) : editingTarget === 'new' ? (
            <View style={styles.presetMgmt}>
              <Text style={styles.headerText}>Create Preset</Text>
              <View style={styles.presetInputs}>
                <TextInput style={styles.input} value={minLen} onChangeText={setMinLen} keyboardType="numeric" />
                <Text style={styles.inputDash}>-</Text>
                <TextInput style={styles.input} value={maxLen} onChangeText={setMaxLen} keyboardType="numeric" />
                <Pressable onPress={createPreset} style={styles.btnCreate}><Text style={styles.btnCreateText}>CREATE</Text></Pressable>
              </View>
            </View>
          ) : (
            <View style={styles.presetMgmt}>
              <Text style={styles.headerText}>Editing Default Rules</Text>
            </View>
          )}
          <Pressable onPress={() => setSize(s => s === 'md' ? 'sm' : 'md')} style={styles.sizeBtn}>
            <Text style={styles.sizeBtnText}>Size: {size}</Text>
          </Pressable>
        </View>

        <View style={styles.tabs}>
          {TABS.map(t => (
            <Pressable key={t} onPress={() => setActiveTab(t)} style={[styles.tab, activeTab === t && styles.tabActive]}>
              <Text style={[styles.tabText, activeTab === t && styles.tabTextActive]}>{t}</Text>
            </Pressable>
          ))}
        </View>

        <ScrollView style={styles.fields}>
          {activeTab === 'global' ? (
            <>
              {renderStepper('Arc Depth', 'arcDepth', 0.05)}
              {renderStepper('Arc Text Length', 'arcTextLength', 0.02)}
              {renderStepper('Arc Center Y', 'arcCenterYOffset', 0.01)}
            </>
          ) : (
            <>
              {renderStepper('Left', 'left', 0.01)}
              {renderStepper('Top', 'top', 0.01)}
              {renderStepper('Width', 'width', 0.01)}
              {renderStepper('Height', 'height', 0.01)}
              {activeTab !== 'icon' && (
                <>
                  {renderStepper('Font Scale', 'fontScale', 0.02)}
                  {renderStepper('Tracking', 'tracking', 0.1)}
                  {renderStepper('Char Factor', 'charFactor', 0.02)}
                  {renderStepper('Min Scale', 'minScale', 0.05)}
                </>
              )}
            </>
          )}
          <Pressable onPress={exportJSON} style={styles.exportBtn}>
            <Text style={styles.exportBtnText}>PRINT JSON TO TERMINAL</Text>
          </Pressable>
        </ScrollView>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.paper },
  previewContainer: { height: 260, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.paperSoft, borderBottomWidth: 1, borderColor: colors.paperBorder },
  controls: { flex: 1, backgroundColor: colors.dashboard },
  rowScroller: { borderBottomWidth: 1, borderColor: colors.darkBorder, paddingVertical: 8 },
  pill: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: radii.pill, backgroundColor: colors.darkBorder, marginHorizontal: 4 },
  pillActive: { backgroundColor: colors.brass },
  pillText: { color: colors.mutedInk, fontFamily: fonts.sansBold, fontSize: 10 },
  pillTextActive: { color: colors.dashboard },
  headerRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', padding: 12, borderBottomWidth: 1, borderColor: colors.darkBorder },
  presetMgmt: { flexDirection: 'row', alignItems: 'center', flex: 1, marginRight: 12 },
  presetInputs: { flexDirection: 'row', alignItems: 'center', marginLeft: 8 },
  input: { backgroundColor: colors.darkBorder, color: colors.creamText, fontFamily: fonts.mono, fontSize: 12, paddingHorizontal: 4, paddingVertical: 2, width: 32, borderRadius: 4, textAlign: 'center' },
  inputDash: { color: colors.mutedInk, marginHorizontal: 4 },
  btnCreate: { backgroundColor: colors.teal, paddingHorizontal: 6, paddingVertical: 4, borderRadius: 4, marginLeft: 8 },
  btnCreateText: { color: '#fff', fontFamily: fonts.sansBold, fontSize: 9 },
  btnDanger: { backgroundColor: colors.red, paddingHorizontal: 6, paddingVertical: 4, borderRadius: 4, marginLeft: 8 },
  btnDangerText: { color: '#fff', fontFamily: fonts.sansBold, fontSize: 9 },
  headerText: { color: colors.creamText, fontFamily: fonts.sansBold, fontSize: 12 },
  sizeBtn: { backgroundColor: colors.darkBorder, paddingHorizontal: 10, paddingVertical: 4, borderRadius: 4 },
  sizeBtnText: { color: colors.creamText, fontFamily: fonts.mono, fontSize: 12 },
  tabs: { flexDirection: 'row', backgroundColor: colors.darkBorder },
  tab: { flex: 1, paddingVertical: 10, alignItems: 'center' },
  tabActive: { backgroundColor: colors.dashboard },
  tabText: { color: colors.subtleText, fontFamily: fonts.sansBold, fontSize: 10, textTransform: 'uppercase' },
  tabTextActive: { color: colors.creamText },
  fields: { flex: 1, padding: 16 },
  stepperRow: { flexDirection: 'row', alignItems: 'center', marginBottom: 12 },
  stepperLabel: { flex: 1, color: colors.creamText, fontFamily: fonts.mono, fontSize: 12 },
  btn: { width: 36, height: 36, backgroundColor: colors.darkBorder, alignItems: 'center', justifyContent: 'center', borderRadius: 4 },
  btnText: { color: colors.creamText, fontSize: 18, fontFamily: fonts.mono },
  stepperValue: { width: 60, textAlign: 'center', color: colors.brassSoft, fontFamily: fonts.mono, fontSize: 14, backgroundColor: colors.appBackground, borderRadius: 4, marginHorizontal: 4, paddingVertical: 4 },
  btnClear: { marginLeft: 8, padding: 8 },
  btnClearText: { color: colors.red, fontFamily: fonts.sansBold, fontSize: 12 },
  exportBtn: { marginTop: 24, backgroundColor: colors.teal, padding: 16, borderRadius: 8, alignItems: 'center' },
  exportBtnText: { color: '#fff', fontFamily: fonts.sansBold, fontSize: 14, letterSpacing: 1 },
});
