/**
 * src/store/useAuthStore.js
 * Zustand store for authentication state.
 * Persists the JWT in AsyncStorage so the user stays logged in.
 */

import { create } from 'zustand';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { getMe } from '../api/auth';

const TOKEN_KEY = '@trotter/jwt';
const USER_KEY  = '@trotter/user';

export const useAuthStore = create((set, get) => ({
  token: null,
  user: null,        // { user_id, email, name }
  status: 'loading', // 'loading' | 'unauthenticated' | 'authenticated'

  /** Called on app boot — restores persisted session. */
  restore: async () => {
    try {
      const [token, userJson] = await Promise.all([
        AsyncStorage.getItem(TOKEN_KEY),
        AsyncStorage.getItem(USER_KEY),
      ]);
      if (!token) { set({ status: 'unauthenticated' }); return; }

      // Validate the token is still good
      await getMe(token);
      const user = userJson ? JSON.parse(userJson) : null;
      set({ token, user, status: 'authenticated' });
    } catch {
      // Token expired or network error — clear and re-auth
      await AsyncStorage.multiRemove([TOKEN_KEY, USER_KEY]);
      set({ token: null, user: null, status: 'unauthenticated' });
    }
  },

  /** Called after successful Google sign-in. */
  login: async ({ access_token, user_id, email, name }) => {
    const user = { user_id, email, name };
    await Promise.all([
      AsyncStorage.setItem(TOKEN_KEY, access_token),
      AsyncStorage.setItem(USER_KEY, JSON.stringify(user)),
    ]);
    set({ token: access_token, user, status: 'authenticated' });
  },

  logout: async () => {
    await AsyncStorage.multiRemove([TOKEN_KEY, USER_KEY]);
    set({ token: null, user: null, status: 'unauthenticated' });
  },
}));
