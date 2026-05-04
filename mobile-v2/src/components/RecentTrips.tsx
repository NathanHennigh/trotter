import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { recentTrips } from '../data/demoTravel';
import { colors, fonts, shadows } from '../theme/tokens';

export function RecentTrips() {
  return (
    <View style={[styles.sheet, shadows.paper]}>
      <View style={styles.handle} />
      <View style={styles.header}>
        <Text style={styles.headerIcon}>AIR</Text>
        <Text style={styles.headerText}>RECENT TRIPS</Text>
        <Text style={styles.viewAll}>VIEW ALL  &gt;</Text>
      </View>
      {recentTrips.map((trip) => (
        <View key={trip.id} style={styles.trip}>
          <View style={[styles.tripBand, { backgroundColor: trip.accent }]}>
            <View style={styles.punch} />
          </View>
          <Text style={styles.dates}>{trip.dates}</Text>
          <View style={styles.tripMain}>
            <Text style={styles.tripTitle}>{trip.title} <Text style={styles.flag}>{trip.countryFlag}</Text></Text>
            <Text style={[styles.route, { color: trip.accent }]}>{trip.route}</Text>
            <Text style={styles.meta}>{trip.miles}  -  {trip.flights}  -  {trip.airlines}</Text>
          </View>
          <View style={styles.stamp}>
            <Text style={[styles.stampText, { color: trip.accent }]}>{trip.stamp}</Text>
          </View>
          <View style={styles.photo}>
            <Text style={styles.photoText}>{trip.imageLabel}</Text>
          </View>
        </View>
      ))}
      <View style={styles.review}>
        <View style={styles.reviewScreen}>
          <Text style={styles.reviewSmall}>NEW FLIGHTS FOUND</Text>
          <Text style={styles.reviewNumber}>12</Text>
        </View>
        <View style={styles.reviewCopy}>
          <Text style={styles.reviewTitle}>12 new flights added</Text>
          <Text style={styles.reviewSub}>from Gmail</Text>
          <Text style={styles.reviewAction}>Tap to review</Text>
        </View>
        <View style={styles.reviewButton}>
          <Text style={styles.reviewButtonText}>REVIEW</Text>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  sheet: {
    borderTopLeftRadius: 28,
    borderTopRightRadius: 28,
    backgroundColor: colors.paper,
    borderWidth: 1,
    borderColor: '#BCA77F',
    paddingHorizontal: 14,
    paddingTop: 16,
    paddingBottom: 12,
    marginTop: -36,
  },
  handle: {
    width: 68,
    height: 7,
    borderRadius: 4,
    alignSelf: 'center',
    backgroundColor: '#A99873',
    marginBottom: 12,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 14,
    paddingHorizontal: 4,
  },
  headerIcon: {
    color: colors.paperInk,
    fontFamily: fonts.sansBold,
    fontSize: 11,
    marginRight: 14,
  },
  headerText: {
    color: colors.paperInk,
    fontFamily: fonts.sansBold,
    fontSize: 15,
    letterSpacing: 0.6,
    flex: 1,
  },
  viewAll: {
    color: colors.red,
    fontFamily: fonts.sansBold,
    fontSize: 13,
  },
  trip: {
    minHeight: 112,
    backgroundColor: '#F2E4C7',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#C9B486',
    marginBottom: 10,
    overflow: 'hidden',
    flexDirection: 'row',
    alignItems: 'center',
  },
  tripBand: {
    width: 30,
    height: '100%',
    alignItems: 'center',
    justifyContent: 'center',
  },
  punch: {
    width: 14,
    height: 14,
    borderRadius: 7,
    backgroundColor: colors.paper,
    borderWidth: 1,
    borderColor: '#B79A68',
  },
  dates: {
    width: 34,
    color: colors.paperInk,
    fontFamily: fonts.sansRegular,
    fontSize: 10,
    transform: [{ rotate: '-90deg' }],
  },
  tripMain: {
    flex: 1,
    paddingVertical: 14,
    paddingRight: 8,
  },
  tripTitle: {
    color: '#16120D',
    fontFamily: fonts.display,
    fontSize: 24,
    lineHeight: 28,
  },
  flag: {
    fontFamily: fonts.sansBold,
    fontSize: 11,
  },
  route: {
    fontFamily: fonts.sansBold,
    fontSize: 15,
    marginTop: 10,
  },
  meta: {
    color: colors.paperInk,
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    marginTop: 8,
  },
  stamp: {
    width: 86,
    height: 72,
    borderRadius: 36,
    borderWidth: 2,
    borderColor: '#AC735A',
    alignItems: 'center',
    justifyContent: 'center',
    transform: [{ rotate: '-8deg' }],
  },
  stampText: {
    fontFamily: fonts.sansBold,
    fontSize: 10,
    textAlign: 'center',
  },
  photo: {
    width: 86,
    height: 72,
    backgroundColor: '#B7C8CA',
    borderWidth: 3,
    borderColor: '#EAD8AF',
    marginRight: 8,
    transform: [{ rotate: '5deg' }],
    alignItems: 'center',
    justifyContent: 'center',
  },
  photoText: {
    color: '#34505B',
    fontFamily: fonts.sansBold,
    fontSize: 9,
  },
  review: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: '#C5AB7B',
    padding: 10,
    backgroundColor: '#EBDAB9',
  },
  reviewScreen: {
    width: 92,
    height: 58,
    borderRadius: 8,
    borderWidth: 3,
    borderColor: '#221F17',
    backgroundColor: '#0C180F',
    padding: 6,
  },
  reviewSmall: {
    color: '#97E16A',
    fontFamily: fonts.mono,
    fontSize: 8,
  },
  reviewNumber: {
    color: '#97E16A',
    fontFamily: fonts.mono,
    fontSize: 30,
  },
  reviewCopy: {
    flex: 1,
  },
  reviewTitle: {
    color: colors.paperInk,
    fontFamily: fonts.sansRegular,
    fontSize: 16,
  },
  reviewSub: {
    color: colors.paperInk,
    fontFamily: fonts.sansRegular,
    fontSize: 15,
    marginTop: 2,
  },
  reviewAction: {
    color: colors.red,
    fontFamily: fonts.sansSemi,
    fontSize: 13,
    marginTop: 4,
  },
  reviewButton: {
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#B89A68',
    backgroundColor: '#E8D9BA',
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  reviewButtonText: {
    color: colors.paperInk,
    fontFamily: fonts.sansBold,
    fontSize: 15,
  },
});
