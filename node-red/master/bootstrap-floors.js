const Docker = require("dockerode");

const docker = new Docker({ socketPath: process.env.DOCKER_SOCKET || "/var/run/docker.sock" });

function envInt(name, fallback) {
  const value = process.env[name];
  if (!value) return fallback;
  const parsed = Number.parseInt(value, 10);
  return Number.isNaN(parsed) ? fallback : parsed;
}

function padFloor(floor) {
  return String(floor).padStart(2, "0");
}

async function ensureImage(image) {
  try {
    await docker.getImage(image).inspect();
    console.log(`[bootstrap] image available: ${image}`);
  } catch (error) {
    if (error.statusCode !== 404) throw error;
    console.log(`[bootstrap] pulling image: ${image}`);
    const stream = await docker.pull(image);
    await new Promise((resolve, reject) => {
      docker.modem.followProgress(stream, (err) => (err ? reject(err) : resolve()));
    });
  }
}

async function getOwnNetworkName() {
  const selfId = process.env.HOSTNAME;
  if (!selfId) {
    throw new Error("HOSTNAME is not available; cannot inspect the master container");
  }

  const info = await docker.getContainer(selfId).inspect();
  const networks = Object.keys(info.NetworkSettings.Networks || {});
  if (!networks.length) {
    throw new Error("nodered_master is not attached to any Docker network");
  }

  return networks[0];
}

async function getOwnDataSource() {
  const selfId = process.env.HOSTNAME;
  if (!selfId) {
    throw new Error("HOSTNAME is not available; cannot inspect the master container");
  }

  const info = await docker.getContainer(selfId).inspect();
  const mount = (info.Mounts || []).find((item) => item.Destination === "/data");
  if (!mount || !mount.Source) {
    throw new Error("nodered_master does not have a /data source mount");
  }

  return mount.Source;
}

async function getOwnCertsSource() {
  const selfId = process.env.HOSTNAME;
  if (!selfId) {
    throw new Error("HOSTNAME is not available; cannot inspect the master container");
  }

  const info = await docker.getContainer(selfId).inspect();
  const mount = (info.Mounts || []).find((item) => item.Destination === "/certs");
  if (!mount || !mount.Source) {
    throw new Error("nodered_master does not have a /certs source mount");
  }

  return mount.Source;
}

async function ensureVolume(name) {
  try {
    await docker.getVolume(name).inspect();
  } catch (error) {
    if (error.statusCode !== 404) throw error;
    await docker.createVolume({
      Name: name,
      Labels: {
        "dic_iot.role": "nodered-floor-data",
      },
    });
  }
}

function desiredEnv(floor) {
  return [
    `TZ=${process.env.TZ || "Africa/Cairo"}`,
    `FLOOR_NUMBER=${floor}`,
    `MQTT_HOST=${process.env.MQTT_HOST || "mosquitto"}`,
    `MQTT_PORT=${process.env.MQTT_PORT || "8883"}`,
    `COAP_HOST=${process.env.COAP_HOST || "campus_engine"}`,
    `NODE_OPTIONS=${process.env.NODE_OPTIONS || ""}`,
    "FLOW_SOURCE=/shared/flows.json",
    "FLOW_TARGET=/data/flows.json",
  ];
}

function hasEnv(containerEnv, key, expectedValue) {
  const entry = (containerEnv || []).find((item) => item.startsWith(`${key}=`));
  return entry === `${key}=${expectedValue}`;
}

function hasPortBinding(info, expectedHostPort) {
  const bindings = info.HostConfig?.PortBindings?.["1880/tcp"] || [];
  return bindings.some((binding) => binding.HostPort === String(expectedHostPort));
}

async function recreateContainer(existing, createOptions) {
  const info = await existing.inspect();
  const running = info.State?.Running;
  if (running) {
    console.log(`[bootstrap] removing outdated container: ${info.Name}`);
    await existing.remove({ force: true });
  } else {
    await existing.remove({ force: true });
  }
  const replacement = await docker.createContainer(createOptions);
  await replacement.start();
}

async function stopWorkers() {
  console.log("[bootstrap] stopping and removing all floor workers...");
  const containers = await docker.listContainers({
    all: true,
    filters: JSON.stringify({ label: ["dic_iot.managed-by=nodered_master"] })
  });

  await Promise.all(containers.map(async (info) => {
    try {
      const container = docker.getContainer(info.Id);
      console.log(`[bootstrap] removing container ${info.Names[0]}...`);
      await container.remove({ force: true });
    } catch (error) {
      console.error(`[bootstrap] error removing ${info.Names[0]}:`, error.message);
    }
  }));
  console.log("[bootstrap] all floor workers removed.");
}

async function ensureWorker(networkName, image, prefix, floorCount, portBase, floor, sharedDataSource, sharedCertsSource) {
  const floorTag = padFloor(floor);
  const name = `${prefix}_${floorTag}`;
  const volumeName = `${prefix}_${floorTag}_data`;
  const workerEnv = desiredEnv(floor);

  await ensureVolume(volumeName);

  const createOptions = {
    name,
    Image: image,
    Env: workerEnv,
    Labels: {
      "dic_iot.role": "nodered-floor",
      "dic_iot.floor": String(floor),
      "dic_iot.managed-by": "nodered_master",
      "dic_iot.floor-count": String(floorCount),
    },
    ExposedPorts: {
      "1880/tcp": {},
    },
    HostConfig: {
      Binds: [
        `${volumeName}:/data`,
        `${sharedDataSource}:/shared:ro`,
        `${sharedCertsSource}:/certs:ro`,
      ],
      RestartPolicy: { Name: "unless-stopped" },
      PortBindings: {
        "1880/tcp": [{ HostPort: String(portBase + floor - 1) }],
      },
      Memory: 1024 * 1024 * 1024, // 1GB
      MemorySwap: 1024 * 1024 * 1024,
    },
    NetworkingConfig: {
      EndpointsConfig: {
        [networkName]: {
          Aliases: [name],
        },
      },
    },
  };

  try {
    const container = docker.getContainer(name);
    const info = await container.inspect();
    const expectedHostPort = portBase + floor - 1;
    const needsRecreate =
      info.Config.Image !== image ||
      !hasEnv(info.Config.Env, "FLOOR_NUMBER", String(floor)) ||
      !hasEnv(info.Config.Env, "MQTT_HOST", process.env.MQTT_HOST || "mosquitto") ||
      !hasEnv(info.Config.Env, "MQTT_PORT", process.env.MQTT_PORT || "8883") ||
      !hasEnv(info.Config.Env, "COAP_HOST", process.env.COAP_HOST || "campus_engine") ||
      !hasEnv(info.Config.Env, "FLOW_SOURCE", "/shared/flows.json") ||
      !hasEnv(info.Config.Env, "FLOW_TARGET", "/data/flows.json") ||
      !hasPortBinding(info, expectedHostPort);

    if (needsRecreate) {
      await recreateContainer(container, createOptions);
      console.log(`[bootstrap] recreated ${name} for floor ${floor}`);
      return;
    }

    if (!info.State?.Running) {
      try {
        await container.start();
      } catch (error) {
        if (error.statusCode !== 304) throw error;
      }
      console.log(`[bootstrap] started existing ${name} for floor ${floor}`);
      return;
    }

    console.log(`[bootstrap] ${name} already running for floor ${floor}`);
  } catch (error) {
    if (error.statusCode !== 404) throw error;
    const container = await docker.createContainer(createOptions);
    await container.start();
    console.log(`[bootstrap] created ${name} for floor ${floor}`);
  }
}

async function main() {
  if (process.argv[2] === "stop") {
    await stopWorkers();
    return;
  }

  const floorCount = envInt("NODE_RED_FLOOR_COUNT", 10);
  const portBase = envInt("NODE_RED_WORKER_PORT_BASE", 1881);
  const image = process.env.NODE_RED_WORKER_IMAGE || "nodered/node-red:latest";
  const prefix = process.env.NODE_RED_WORKER_PREFIX || "nodered_floor";
  const networkName = await getOwnNetworkName();
  const sharedDataSource = await getOwnDataSource();
  const sharedCertsSource = await getOwnCertsSource();

  console.log(`[bootstrap] network=${networkName} floors=${floorCount} image=${image}`);
  await ensureImage(image);

  for (let floor = 1; floor <= floorCount; floor += 1) {
    await ensureWorker(networkName, image, prefix, floorCount, portBase, floor, sharedDataSource, sharedCertsSource);
  }
}

main().catch((error) => {
  console.error("[bootstrap] failed:", error);
  process.exit(1);
});
