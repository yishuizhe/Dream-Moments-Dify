package com.nana.phone;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Base64;

import java.security.SecureRandom;

final class PhoneSettings {
    private static final String PREFS = "nana_phone";
    private static final String TOKEN = "token";
    private static final String PORT = "port";
    static final int DEFAULT_PORT = 8765;

    private PhoneSettings() {}

    static String token(Context context) {
        SharedPreferences prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        String token = prefs.getString(TOKEN, "");
        if (token == null || token.length() < 32) {
            byte[] bytes = new byte[32];
            new SecureRandom().nextBytes(bytes);
            token = Base64.encodeToString(bytes, Base64.URL_SAFE | Base64.NO_WRAP | Base64.NO_PADDING);
            prefs.edit().putString(TOKEN, token).apply();
        }
        return token;
    }

    static int port(Context context) {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getInt(PORT, DEFAULT_PORT);
    }

    static void setPort(Context context, int port) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putInt(PORT, port).apply();
    }

    static String regenerateToken(Context context) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().remove(TOKEN).apply();
        return token(context);
    }
}
