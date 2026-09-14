/** Dormant RPC adapter. Importing this file does not intercept Steam or submit
 * power. Production mounting waits for installed-client and combined review.
 */
import { callable } from "@decky/api";
import type { PowerAction, PowerRequestPort } from "./power-request-coordinator";

const execute = callable<[boolean, string, string, PowerAction, boolean, string, string], unknown>(
  "execute_egpu_disconnect",
);
const status = callable<[string], unknown>("get_egpu_disconnect_status");

export const powerRequestPort: PowerRequestPort = {
  execute: (action, attachment, requestId) => execute(true, "", "disconnect", action, true, attachment, requestId),
  readStatus: () => status("power_status"),
};
