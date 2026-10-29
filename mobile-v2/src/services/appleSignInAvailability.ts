import Constants from 'expo-constants';
import { Platform } from 'react-native';

export function isAppleSignInEnabled(): boolean {
  return Platform.OS === 'ios' && Constants.expoConfig?.extra?.appleSignInEnabled === true;
}
