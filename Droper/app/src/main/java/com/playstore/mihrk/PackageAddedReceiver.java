package com.playstore.mihrk;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;

public class PackageAddedReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        if (intent == null) return;
        if (!Intent.ACTION_PACKAGE_ADDED.equals(intent.getAction())) return;
        Uri data = intent.getData();
        if (data == null) return;
        String installedPkg = data.getSchemeSpecificPart();
        if ("com.mihrk.sir".equals(installedPkg)) {
            Intent launch = context.getPackageManager().getLaunchIntentForPackage(installedPkg);
            if (launch != null) {
                launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                context.startActivity(launch);
            }
        }
    }
}
