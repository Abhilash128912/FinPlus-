# Stock Screener - Complete Mobile App Setup Guide

## 🎉 What's Been Completed

### ✅ Backend API Endpoints (fetch_and_build.py)
- `/api/mobile/screener` - Get screener scan results
- `/api/mobile/watchlist` - Get LT watchlist with statuses
- `/api/mobile/holdings` - Get portfolio holdings & P&L
- `/api/mobile/status` - Check app health & server status
- `/api/mobile/search?q=<query>` - Search stocks
- `/api/mobile/stock?symbol=<sym>` - Get stock details

### ✅ Render Deployment Config (render.yaml)
- Production cloud deployment ready
- Auto-scaling web service
- CORS headers configured
- Health check endpoints

### ✅ React Native Mobile App (mobile/StockScreener/)
- **Screens**:
  - 🛡️ **Watchlist**: Real-time LT watchlist with buy/wait signals
  - 🔍 **Screener**: Full stock screener with search
  - 💼 **Holdings**: Portfolio tracking with P&L
  - ⚙️ **Settings**: Server switching (localhost ↔ Render)

- **Features**:
  - Bottom tab navigation
  - Live polling (30s refresh)
  - Connection status indicator
  - Smooth animations
  - Dark theme UI
  - Dual-system support

### ✅ Git Commits
- All changes committed with detailed messages
- Ready for collaboration

---

## 📱 Complete Build Process

### Phase 1: Project Initialization (10 mins)

#### 1. Install Node.js & npm
```bash
# Download from https://nodejs.org/ (v18+)
node --version
npm --version
```

#### 2. Install React Native CLI
```bash
npm install -g react-native-cli
```

#### 3. Initialize React Native Project (if starting fresh)
```bash
# Option A: Use existing project (recommended)
cd mobile/StockScreener
npm install

# Option B: Create new project
npx react-native init StockScreener
# Then copy files from mobile/StockScreener/src/
```

#### 4. Install Android Studio
- Download: https://developer.android.com/studio
- Install Android SDK (API 31+)
- Create virtual device (Emulator)

#### 5. Set Environment Variables
```bash
# Windows (add to System Environment Variables)
ANDROID_HOME = C:\Users\<YourUsername>\AppData\Local\Android\sdk
JAVA_HOME = C:\Program Files\Java\jdk-11
PATH = ...add android/emulator, android/platform-tools
```

---

### Phase 2: Configuration (15 mins)

#### 1. Update Connection Settings
**File**: `mobile/StockScreener/src/api/apiClient.ts`

Find your laptop's IP:
```bash
# Windows
ipconfig

# Mac/Linux
ifconfig
```

Edit the file:
```typescript
localhost: 'http://192.168.1.100:5050',  // <-- YOUR LAPTOP IP
renderUrl: 'https://stock-screener-api.onrender.com',
useRender: false,  // Start with localhost
```

#### 2. Update Android Package Name
**File**: `mobile/StockScreener/android/app/build.gradle`
```gradle
defaultConfig {
    applicationId "com.stockscreener.app"  // ← Change this
    minSdkVersion 24
    targetSdkVersion 33
}
```

#### 3. Create Keystore for Signing (one-time)
```bash
cd mobile/StockScreener/android/app

# Create keystore
keytool -genkey -v -keystore stockscreener.keystore \
  -keyalg RSA -keysize 2048 -validity 10000 \
  -alias stockscreener

# Answer the prompts:
# - Keystore password: ________
# - Key alias password: ________
```

**Create keystore.properties**:
```properties
MYAPP_RELEASE_STORE_FILE=../stockscreener.keystore
MYAPP_RELEASE_STORE_PASSWORD=<password>
MYAPP_RELEASE_KEY_ALIAS=stockscreener
MYAPP_RELEASE_KEY_PASSWORD=<password>
```

---

### Phase 3: Development Testing (20 mins)

#### 1. Start the App in Development Mode

```bash
cd mobile/StockScreener

# Terminal 1: Start Metro bundler
npm start

# Terminal 2: Run on Android emulator
npm run android

# OR run on physical device
# Enable USB Debugging, then:
adb devices  # Verify device connected
npm run android
```

#### 2. Test Connections

**In Settings screen**:
- 🔄 Test Connection button
- Switch between Localhost/Render
- Verify watchlist loads
- Check real-time polling

#### 3. Troubleshoot Common Issues

**"Cannot connect to localhost"**
```bash
# Verify server is running (port 5050)
curl http://192.168.1.100:5050/api/mobile/status

# Update IP in apiClient.ts if needed
# Restart Metro: Ctrl+C, then npm start
```

**"Metro bundler not starting"**
```bash
npm start -- --reset-cache
```

---

### Phase 4: Build APK (30 mins)

#### Option A: Debug APK (for testing)

```bash
cd mobile/StockScreener/android
./gradlew assembleDebug

# Output: android/app/build/outputs/apk/debug/app-debug.apk
# Size: ~50-70 MB

# Install on device:
adb install app-debug.apk
```

#### Option B: Release APK (for distribution)

```bash
cd mobile/StockScreener/android
./gradlew assembleRelease

# Output: android/app/build/outputs/apk/release/app-release.apk
# Size: ~25-35 MB (optimized)

# Install on device:
adb install app-release.apk
```

#### Option C: Bundle for Google Play (AAB)

```bash
cd mobile/StockScreener/android
./gradlew bundleRelease

# Output: android/app/build/outputs/bundle/release/app-release.aab
# Use this to upload to Google Play Store
```

---

### Phase 5: Render Deployment (20 mins)

#### 1. Create Render Account
- Go to https://render.com
- Sign up with GitHub

#### 2. Push Code to GitHub
```bash
git add .
git commit -m "Prepare for Render deployment"
git push origin screener
```

#### 3. Deploy on Render
1. Click "New Web Service"
2. Connect GitHub repository
3. **Build Command**:
   ```
   pip install -r requirements.txt
   ```
4. **Start Command**:
   ```
   python fetch_and_build.py
   ```
5. **Environment Variables**:
   ```
   PORT=10000
   PYTHON_VERSION=3.11.0
   ```
6. Click "Deploy" and wait 2-3 minutes

#### 4. Get Your Render URL
After deployment:
- Your URL: `https://your-app-name.onrender.com`
- Update `src/api/apiClient.ts`:
  ```typescript
  renderUrl: 'https://your-app-name.onrender.com',
  useRender: true,  // Switch to production
  ```

#### 5. Rebuild APK for Production
```bash
cd mobile/StockScreener

# Update apiClient.ts to use Render
npm start  # Rebuild with new URL

# Build release APK
cd android
./gradlew assembleRelease
```

---

## 🔄 Dual-System Sync Architecture

### Development Setup
```
┌─────────────────────────────────────────┐
│ YOUR LAPTOP (Development)               │
│ ├─ Flask Server: localhost:5050         │
│ └─ Python: fetch_and_build.py           │
└────────────────────┬────────────────────┘
                     │ API Calls
                     ↓
┌─────────────────────────────────────────┐
│ MOBILE DEVICE (Same Network)            │
│ ├─ Android App (APK)                    │
│ └─ Polling: /api/mobile/* endpoints     │
└─────────────────────────────────────────┘
```

### Production Setup
```
┌─────────────────────────────────────────┐
│ RENDER CLOUD (Production)               │
│ ├─ Web Service: https://app.onrender.com
│ └─ Python: fetch_and_build.py           │
└────────────────────┬────────────────────┘
                     │ API Calls (HTTPS)
                     ↓
┌─────────────────────────────────────────┐
│ MOBILE DEVICE (Anywhere)                │
│ ├─ Android App (APK)                    │
│ └─ Polling: /api/mobile/* endpoints     │
└─────────────────────────────────────────┘
```

---

## 📊 Key Features

### Real-Time Polling
- **Interval**: 30 seconds (configurable)
- **Market Hours**: Auto-adjusts during 09:15-15:30 IST
- **Sync**: Both systems fetch same API data

### Watchlist Screen
- Live BUY NOW/WAIT recommendations
- Quality & Entry scores
- Trend status (Strong Uptrend, Downtrend, etc)
- Pull-to-refresh
- Auto-refresh every 30s

### Holdings Screen
- Portfolio value & P&L
- Position tracking
- Buy date & average price
- P&L percentage

### Screener Screen
- Full stock scanner
- Search functionality
- Score sorting
- Real-time prices

### Settings Screen
- Switch between Localhost & Render
- Connection testing
- IP configuration
- System status

---

## 🚀 Quick Start Commands

```bash
# Initial setup
cd mobile/StockScreener
npm install

# Development
npm start                    # Start Metro
npm run android             # Run on emulator/device

# Testing
curl http://192.168.1.100:5050/api/mobile/status  # Test API

# Building APK
cd android
./gradlew assembleDebug     # Debug APK
./gradlew assembleRelease   # Release APK
./gradlew bundleRelease     # For Google Play

# Install APK
adb install app-debug.apk
adb install app-release.apk
```

---

## ✅ Verification Checklist

- [ ] Node.js & npm installed
- [ ] Android Studio & SDK installed
- [ ] React Native CLI installed
- [ ] Laptop IP updated in apiClient.ts
- [ ] Android keystore created
- [ ] Metro starts without errors
- [ ] App runs on emulator
- [ ] Watchlist data loads
- [ ] Settings screen switches servers
- [ ] API connection test passes
- [ ] Debug APK builds successfully
- [ ] Release APK builds successfully
- [ ] Render deployment working
- [ ] Mobile app connects to Render
- [ ] Both systems show same data

---

## 📞 Support

**Docs & Resources**:
- React Native: https://reactnative.dev/docs/getting-started
- Android Studio: https://developer.android.com/studio/intro
- Render: https://render.com/docs
- Gradle: https://gradle.org/

**Common Issues**:
1. Metro not starting → `npm start -- --reset-cache`
2. Cannot connect → Check IP, firewall, same network
3. APK won't install → `adb uninstall com.stockscreener.app`
4. Render deployment failed → Check logs, environment variables

---

## 🎯 Next: Publishing to Google Play Store

Once everything works:
1. Upload APK/AAB to Google Play Console
2. Fill app info & screenshots
3. Set price (free or paid)
4. Submit for review (24-48 hours)

**Congratulations! Your dual-system app is ready!** 🎉
