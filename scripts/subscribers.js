// Two-UE subscriber profile. New stands have independent 5GS AKA credentials;
// existing stands may use the complete legacy SUBSCRIBER_* credential set.
const required = (name) => {
  const value = process.env[name];
  if (!value) throw new Error(`Missing required environment variable ${name}`);
  return value;
};
const credential = (ue) => {
  const names = [`UE${ue}_5GS_K`, `UE${ue}_5GS_OPC`, `UE${ue}_5GS_AMF`];
  const selected = names.some((name) => process.env[name])
    ? names : ["SUBSCRIBER_K", "SUBSCRIBER_OPC", "SUBSCRIBER_AMF"];
  return selected.map(required);
};

const profiles = [1, 2].map((ue) => ({
  imsi: required(`UE${ue}_IMSI`),
  keys: credential(ue)
}));

db = db.getSiblingDB("open5gs");

for (const { imsi, keys } of profiles) {
  const [K, OPC, AMF] = keys;
  const existing = db.subscribers.findOne({ imsi: imsi });
  if (existing) {
    const security = existing.security || {};
    // This image's mongosh transpiler loses the receiver in optional method calls.
    const same = ["k", "opc", "amf"].every((field, index) =>
      typeof security[field] === "string"
      && security[field].toLowerCase() === keys[index].toLowerCase());
    if (!same) throw new Error(`5GS AKA mismatch for IMSI ${imsi}; explicit migration required`);
  }
  // Insert the initial profile once. Existing Open5GS records may contain
  // authentication state and operator edits that provisioning must preserve.
  db.subscribers.updateOne({ imsi: imsi }, { $setOnInsert: {
    imsi: imsi,
    security: { k: K, amf: AMF, opc: OPC, op: null },
    subscriber_status: 0,
    access_restriction_data: 32,
    network_access_mode: 0,
    subscribed_rau_tau_timer: 12,
    ambr: {
      uplink: { value: 1, unit: 3 },
      downlink: { value: 1, unit: 3 }
    },
    slice: [
      {
        sst: 1,
        default_indicator: true,
        session: [
          {
            name: "internet",
            type: 3,
            qos: {
              index: 9,
              arp: {
                priority_level: 8,
                pre_emption_capability: 1,
                pre_emption_vulnerability: 1
              }
            },
            ambr: {
              uplink: { value: 1, unit: 3 },
              downlink: { value: 1, unit: 3 }
            },
            pcc_rule: []
          },
          {
            name: "ims",
            type: 3,
            qos: {
              index: 5,
              arp: {
                priority_level: 8,
                pre_emption_capability: 1,
                pre_emption_vulnerability: 1
              }
            },
            ambr: {
              uplink: { value: 1, unit: 3 },
              downlink: { value: 1, unit: 3 }
            },
            pcc_rule: []
          }
        ]
      }
    ]
  } }, { upsert: true });
  print("ensured subscriber " + imsi);
}

printjson(db.subscribers.find({}, { imsi: 1, _id: 0 }).toArray());
