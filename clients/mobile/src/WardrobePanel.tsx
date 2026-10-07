import {useAppTheme, useThemedStyles, type AppColors} from './app-theme';
import {useState} from 'react';
import {ActivityIndicator, ScrollView, StyleSheet, Text, View} from 'react-native';
import {Check, ChevronLeft, ChevronRight, RefreshCw} from 'lucide-react-native';
import {PajamaBear} from './PajamaBear';
import {outfitById, outfits, OutfitId} from './wardrobe';
import type {WardrobeController} from './useWardrobe';
import {TactilePressable} from './experience/primitives';

export function WardrobeEntry({wardrobe, onPress}: {wardrobe: WardrobeController; onPress: () => void}) {
  const {colors: c} = useAppTheme();
  const s = useThemedStyles(makeStyles);

  const {state} = wardrobe;
  return <TactilePressable accessibilityLabel="打开睡衣衣橱，给小熊换一套睡衣" onPress={onPress} style={s.entry}>
    <View style={s.entryWords}><Text style={s.entryTitle}>小熊的衣橱</Text><Text style={s.description}>选一套喜欢的，陪你过今天。</Text><View style={s.entryLink}><Text style={s.link}>换一套睡衣</Text><ChevronRight size={16} color={c.ink}/></View></View>
    <PajamaBear outfit={state.outfit} size={146}/>
  </TactilePressable>;
}

export function Wardrobe({wardrobe, onBack}: {wardrobe: WardrobeController; onBack: () => void}) {
  const {colors: c} = useAppTheme();
  const s = useThemedStyles(makeStyles);

  const {state, session} = wardrobe;
  const [preview, setPreview] = useState<OutfitId | null>(null);
  const selected = preview || state.outfit, outfit = outfitById(selected);
  const changed = selected !== state.outfit;
  return <View style={s.page}>
    <View style={s.heading}><TactilePressable onPress={onBack} accessibilityLabel="返回我的" style={s.back}><ChevronLeft size={23} color={c.ink}/></TactilePressable><Text style={s.title}>睡衣衣橱</Text></View>
    <View style={s.stage}>
      <PajamaBear outfit={selected} size={218}/>
      <Text style={s.outfitTitle}>{outfit.name}</Text><Text style={s.description}>{outfit.detail}</Text>
    </View>
    <View style={s.collectionHeading}><Text style={s.link}>挑一套试穿</Text><Text style={s.description}>8 套 · 左右滑动</Text></View>
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.rail} accessibilityRole="radiogroup" accessibilityLabel="睡衣款式">
      {outfits.map(item => <TactilePressable key={item.id} accessibilityRole="radio" accessibilityLabel={item.name} accessibilityHint="预览这套睡衣，点穿这套后保存" accessibilityState={{checked: selected === item.id}} disabled={state.saving}
        onPress={() => setPreview(item.id)} style={[s.option, selected === item.id && s.optionSelected]}>
        <PajamaBear outfit={item.id} size={100}/>
        <View style={s.optionLabel}><View style={[s.swatch, {backgroundColor: item.swatch}]}/><Text style={s.optionName}>{item.name}</Text></View>
        <View style={s.check}>{selected === item.id ? <Check size={15} color={c.ink}/> : null}</View>
      </TactilePressable>)}
    </ScrollView>
    <TactilePressable disabled={!state.ready || state.saving || !changed} accessibilityLabel={changed ? `穿上${outfit.name}` : `已穿上${outfit.name}`} accessibilityState={{busy: state.saving}}
      onPress={() => {void session.save(selected);}} style={[s.apply, !changed && s.applied]}>
      {state.saving || state.loading ? <ActivityIndicator size="small" color={c.ink}/> : !changed ? <Check size={18} color={c.ink}/> : null}
      <Text accessibilityLiveRegion="polite" style={s.applyLabel}>{state.loading ? '正在打开衣橱' : !state.ready ? '等待读取穿搭' : state.saving ? '正在保存' : changed ? '穿这套' : '已穿上'}</Text>
    </TactilePressable>
    {state.error ? <View style={s.error}><Text accessibilityLiveRegion="polite" style={s.errorText}>{state.error}</Text>{!state.ready ? <TactilePressable style={s.retry} onPress={() => {void session.load();}} accessibilityLabel="重新读取衣橱"><RefreshCw size={18} color={c.ink}/><Text style={s.link}>重试</Text></TactilePressable> : null}</View> : null}
    <Text style={s.footnote}>穿搭保存在这台手机，跟随当前身份。随时可以再换。</Text>
  </View>;
}

const makeStyles = (c: AppColors) => StyleSheet.create({
  page: {gap: 12, paddingBottom: 12}, back: {width: 44, height: 44, alignItems: 'center', justifyContent: 'center', borderRadius: 22, backgroundColor: c.surface},
  heading: {flexDirection: 'row', alignItems: 'center', gap: 12, marginBottom: 4}, title: {fontSize: 26, lineHeight: 35, fontWeight: '500', color: c.ink, letterSpacing: -.5},
  description: {fontSize: 13, lineHeight: 22, color: c.muted, flexShrink: 1},
  stage: {alignItems: 'center', paddingTop: 8, paddingBottom: 16, gap: 6, borderRadius: 28, backgroundColor: c.surface},
  outfitTitle: {fontSize: 19, lineHeight: 28, fontWeight: '500', color: c.ink},
  apply: {minHeight: 48, borderRadius: 24, padding: 12, flexDirection: 'row', gap: 7, alignItems: 'center', justifyContent: 'center', backgroundColor: c.soft},
  applied: {backgroundColor: c.surface}, applyLabel: {fontSize: 16, lineHeight: 23, color: c.ink, fontWeight: '500'},
  collectionHeading: {flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 3},
  rail: {gap: 9, paddingBottom: 2}, option: {width: 120, alignItems: 'center', borderRadius: 21, paddingTop: 12, paddingBottom: 12, backgroundColor: c.surface, borderWidth: 1, borderColor: 'transparent'},
  optionSelected: {backgroundColor: c.surface, borderColor: c.accent},
  optionLabel: {flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 8}, optionName: {fontSize: 13, lineHeight: 21, color: c.ink, flexShrink: 1},
  swatch: {width: 9, height: 9, borderRadius: 5}, check: {position: 'absolute', top: 10, right: 10, width: 17, height: 17},
  footnote: {fontSize: 11, lineHeight: 19, color: c.muted, textAlign: 'center', paddingHorizontal: 12},
  error: {gap: 4, paddingHorizontal: 8}, errorText: {fontSize: 13, lineHeight: 22, color: c.danger}, retry: {minHeight: 44, flexDirection: 'row', alignItems: 'center', gap: 6},
  entry: {flexDirection: 'row', alignItems: 'center', borderRadius: 28, paddingLeft: 20, paddingVertical: 12, backgroundColor: c.surface},
  entryWords: {flex: 1, gap: 8}, entryTitle: {fontSize: 20, lineHeight: 29, fontWeight: '500', color: c.ink}, entryLink: {flexDirection: 'row', gap: 2, alignItems: 'center', marginTop: 7}, link: {fontSize: 14, lineHeight: 22, color: c.ink},
});
