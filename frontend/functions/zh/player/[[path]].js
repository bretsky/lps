// /zh/player/<slug>: proxied from the i18n branch deployment (see functions-shared/i18n-proxy.js).
import { proxyProfile } from "../../../functions-shared/i18n-proxy.js";

export const onRequest = proxyProfile;
