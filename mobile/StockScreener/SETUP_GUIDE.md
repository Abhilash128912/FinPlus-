# Stock Screener Mobile App - Setup & Build Guide

## Prerequisites

### Install Required Tools

1. **Node.js & npm** (v18+)
   ```bash
   # Download from https://nodejs.org/
   node --version  # Verify
   npm --version
   ```

2. **React Native CLI**
   ```bash
   npm install -g react-native-cli
   ```

3. **Android Studio** (for APK building)
   - Download: https://developer.android.com/studio
   - Install Android SDK (API 31+)
   - Set ANDROID_HOME environment variable

4. **Java Development Kit (JDK)** (v11+)
   ```bash
   java -version  # Verify
   ```

---

## Project Setup

### 1. Install Dependencies

```bash
cd mobile/StockScreener
npm install
```

### 2. Configure Connection

**Edit `src/api/apiClient.ts`:**
- Change `localhost` IP to your laptop's IP address (find with `ipconfig` on Windows)
- Set Render URL after deployment (https://stock-screener-api.onrender.com)

Example:
```typescript
localhost: 'http://192.168.1.100:5050',  // Your laptop IP:5050
renderUrl: 'https://stock-screener-api.onrender.com',  // After Render deploy
```

### 3. Update Android Package Name

**Edit `android/app/build.gradle`:**
```gradle
applicationId "com.stockscreener.app"
```

**Edit `android/app/src/AndroidManifest.xml`:**
```xml
<manifest package="com.stockscreener.app">
```

---

## Development

### Run on Android Emulator

```bash
# Start Metro bundler
npm start

# In new terminal:
npm run android
```

### Run on Physical Device

```bash
# Enable USB Debugging on device
adb devices  # Verify device is connected

npm run android
```

---

## Build APK

### Debug APK (for testing)

```bash
cd android
./gradlew assembleDebug
# APK: android/app/build/outputs/apk/debug/app-debug.apk
```

### Release APK (for production)

#### 1. Create Keystore (one-time only)

```bash
keytool -genkey -v -keystore stockscreener.keystore -keyalg RSA -keysize 2048 -validity 10000 -alias stockscreener
```

#### 2. Add Keystore to Gradle

**Create `android/app/keystore.properties`:**
```properties
MYAPP_RELEASE_STORE_FILE=../stockscreener.keystore
MYAPP_RELEASE_STORE_PASSWORD=<password>
MYAPP_RELEASE_KEY_ALIAS=stockscreener
MYAPP_RELEASE_KEY_PASSWORD=<password>
```

#### 3. Build Release APK

```bash
cd android
./gradlew assembleRelease
# APK: android/app/build/outputs/apk/release/app-release.apk
```

#### 4. Build AAB (for Google Play Store)

```bash
./gradlew bundleRelease
# AAB: android/app/build/outputs/bundle/release/app-release.aab
```

---

## Render Deployment

### 1. Push Code to GitHub

```bash
git add .
git commit -m "Add React Native mobile app"
git push origin main
```

### 2. Connect Render

1. Go to https://render.com
2. Create new Web Service
3. Connect GitHub repo
4. Set Build Command: `pip install -r requirements.txt`
5. Set Start Command: `python fetch_and_build.py`
6. Add Environment Variables:
   - `PORT=10000`
   - `PYTHON_VERSION=3.11.0`
7. Deploy

### 3. Update Mobile App with Render URL

Once deployed, update `src/api/apiClient.ts`:
```typescript
renderUrl: 'https://your-app.onrender.com',
useRender: true,  // Switch to Render in production
```

---

## Folder Structure

```
mobile/StockScreener/
├── src/
│   ├── api/
│   │   └── apiClient.ts          # API client for both localhost & Render
│   ├── screens/
│   │   ├── WatchlistScreen.tsx    # LT Watchlist view
│   │   ├── ScreenerScreen.tsx     # Full screener scan
│   │   ├── HoldingsScreen.tsx     # Portfolio view
│   │   └── SettingsScreen.tsx     # Settings & server switch
│   ├── components/
│   │   ├── StockCard.tsx          # Stock item component
│   │   └── StatusBadge.tsx        # Status badge component
│   ├── navigation/
│   │   └── Navigation.tsx         # Tab & stack navigation
│   └── App.tsx                    # Main app entry point
├── android/                       # Android native code
├── package.json
├── app.json
├── babel.config.js
├── metro.config.js
└── tsconfig.json
```

---

## Dual System Architecture

### Development
- **Laptop**: localhost:5050 (Python Flask server)
- **Mobile**: Connects to laptop IP via `apiClient.ts`
- **Sync**: Real-time API polling (10s during market hours)

### Production
- **Render Cloud**: https://stock-screener-api.onrender.com
- **Mobile APK**: Connects to Render for live data
- **Sync**: Automatic - both systems fetch same API

---

## Troubleshooting

### "Cannot connect to localhost"
- Update IP in `apiClient.ts` to your laptop's actual IP
- Ensure firewall allows port 5050
- Verify laptop and phone are on same network

### "Metro bundler not starting"
```bash
npm start -- --reset-cache
```

### "Gradle build fails"
```bash
cd android
./gradlew clean
./gradlew assembleDebug
```

### "APK won't install"
```bash
adb uninstall com.stockscreener.app
npm run android
```

---

## Next Steps

1. ✅ Complete setup
2. ✅ Test on emulator/device
3. ✅ Build debug APK
4. ✅ Deploy to Render
5. ✅ Build release APK
6. ✅ Publish to Google Play Store (optional)

---

## Support Resources

- React Native Docs: https://reactnative.dev/
- Android Studio: https://developer.android.com/studio/intro
- Render Docs: https://render.com/docs
