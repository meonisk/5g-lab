// Two-UE subscriber profile, identical identity parameters to asterisk_legacy.
// IMSI 001010000000001 / 001010000000002, shared K/OPc, DNN internet, SST 1.
const required = (name) => {
  const value = process.env[name];
  if (!value) throw new Error(`Missing required environment variable ${name}`);
  return value;
};
const K = required("SUBSCRIBER_K");
const OPC = required("SUBSCRIBER_OPC");
const AMF = "8000";

const imsis = [required("UE1_IMSI"), required("UE2_IMSI")];

db = db.getSiblingDB("open5gs");

for (const imsi of imsis) {
  db.subscribers.deleteMany({ imsi: imsi });
  db.subscribers.insertOne({
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
  });
  print("added subscriber " + imsi);
}

printjson(db.subscribers.find({}, { imsi: 1, _id: 0 }).toArray());
