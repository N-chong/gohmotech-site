(function (window, document) {
  'use strict';

  function createApprovedGoatHouseViewer(container) {
      const THREE = window.THREE;
      if (!THREE || !container) return null;

      const loading = container.querySelector('.goat-house-loading');
      const initialLightOn = container.dataset.lightState === 'on';
      let destroyed = false;
      let animationFrameId = null;
      const mobile = window.matchMedia('(max-width: 767px)').matches;
      let inViewport = true;
      let dirtyFrames = 1;
      let initialized = false;
      const scene = new THREE.Scene();
      scene.background = new THREE.Color(0x9bc6dc);
      scene.fog = new THREE.Fog(0x9bc6dc, 30, 66);

      const initialWidth = Math.max(container.clientWidth, 1);
      const initialHeight = Math.max(container.clientHeight, 1);
      const camera = new THREE.PerspectiveCamera(48, initialWidth / initialHeight, 0.1, 120);
      camera.position.set(8.6, 5.4, 10.2);

      const renderer = new THREE.WebGLRenderer({ antialias: !mobile, powerPreference: 'low-power' });
      renderer.setPixelRatio(Math.min(devicePixelRatio, mobile ? 1 : 1.75));
      renderer.setSize(initialWidth, initialHeight, false);
      renderer.shadowMap.enabled = true;
      renderer.shadowMap.type = THREE.PCFSoftShadowMap;
      renderer.outputEncoding = THREE.sRGBEncoding;
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 1.05;
      renderer.domElement.className = 'goat-house-canvas';
      container.appendChild(renderer.domElement);

      const maxAnisotropy = Math.min(4, renderer.capabilities.getMaxAnisotropy());

      function canvasTexture(draw, width = 256, height = 256) {
        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext('2d');
        draw(ctx, width, height);
        const texture = new THREE.CanvasTexture(canvas);
        texture.anisotropy = maxAnisotropy;
        return texture;
      }

      const woodTexture = canvasTexture((ctx, w, h) => {
        ctx.fillStyle = '#9a673e';
        ctx.fillRect(0, 0, w, h);
        for (let i = 0; i < 34; i++) {
          const y = Math.random() * h;
          ctx.strokeStyle = `rgba(59,31,16,${0.05 + Math.random() * 0.11})`;
          ctx.lineWidth = 1 + Math.random() * 2;
          ctx.beginPath();
          ctx.moveTo(0, y);
          ctx.bezierCurveTo(w * .28, y + Math.random() * 8 - 4, w * .68, y + Math.random() * 8 - 4, w, y + Math.random() * 5 - 2);
          ctx.stroke();
        }
      });
      woodTexture.wrapS = woodTexture.wrapT = THREE.RepeatWrapping;
      woodTexture.repeat.set(2.5, 2.5);

      const grassTexture = canvasTexture((ctx, w, h) => {
        ctx.fillStyle = '#668f43';
        ctx.fillRect(0, 0, w, h);
        for (let i = 0; i < 1200; i++) {
          const tone = 72 + Math.floor(Math.random() * 65);
          ctx.fillStyle = `rgba(${52 + Math.floor(Math.random() * 35)},${tone},${35 + Math.floor(Math.random() * 25)},.35)`;
          ctx.fillRect(Math.random() * w, Math.random() * h, 1.5, 1.5);
        }
      });
      grassTexture.wrapS = grassTexture.wrapT = THREE.RepeatWrapping;
      grassTexture.repeat.set(14, 14);

      const materials = {
        wood: new THREE.MeshStandardMaterial({ map: woodTexture, color: 0xc38a59, roughness: .84 }),
        woodDark: new THREE.MeshStandardMaterial({ color: 0x60402b, roughness: .92 }),
        bamboo: new THREE.MeshStandardMaterial({ color: 0xb99653, roughness: .8 }),
        bambooDark: new THREE.MeshStandardMaterial({ color: 0x77602f, roughness: .88 }),
        metal: new THREE.MeshStandardMaterial({ color: 0x879197, roughness: .45, metalness: .55, side: THREE.DoubleSide }),
        metalDark: new THREE.MeshStandardMaterial({ color: 0x515b61, roughness: .5, metalness: .55 }),
        blue: new THREE.MeshStandardMaterial({ color: 0x147cca, roughness: .34, metalness: .18 }),
        blueDark: new THREE.MeshStandardMaterial({ color: 0x075a9a, roughness: .45, metalness: .18 }),
        black: new THREE.MeshStandardMaterial({ color: 0x182020, roughness: .55 }),
        feeder: new THREE.MeshStandardMaterial({ color: 0xa97039, roughness: .62, metalness: .06, side: THREE.DoubleSide }),
        feederEdge: new THREE.MeshStandardMaterial({ color: 0x604022, roughness: .7 }),
        feed: new THREE.MeshStandardMaterial({ color: 0xcbb368, roughness: .95 }),
        concrete: new THREE.MeshStandardMaterial({ color: 0x737b72, roughness: .95 }),
        grass: new THREE.MeshStandardMaterial({ map: grassTexture, color: 0x8ab762, roughness: 1 }),
        leaf: new THREE.MeshStandardMaterial({ color: 0x426f38, roughness: 1, flatShading: true }),
        leafLight: new THREE.MeshStandardMaterial({ color: 0x66944a, roughness: 1, flatShading: true }),
        dirt: new THREE.MeshStandardMaterial({ color: 0x8a6747, roughness: 1 })
      };

      function mesh(geometry, material, position, rotation, shadows = true) {
        const object = new THREE.Mesh(geometry, material);
        if (position) object.position.set(...position);
        if (rotation) object.rotation.set(...rotation);
        object.castShadow = shadows;
        object.receiveShadow = shadows;
        return object;
      }

      // Sun and soft outdoor illumination.
      const hemisphere = new THREE.HemisphereLight(0xdff3ff, 0x38502d, 1.03);
      scene.add(hemisphere);
      const sun = new THREE.DirectionalLight(0xfff1d1, 2.05);
      sun.position.set(-11, 18, 9);
      sun.castShadow = true;
      sun.shadow.mapSize.set(1024, 1024);
      sun.shadow.camera.left = -15;
      sun.shadow.camera.right = 15;
      sun.shadow.camera.top = 15;
      sun.shadow.camera.bottom = -15;
      sun.shadow.camera.near = 1;
      sun.shadow.camera.far = 42;
      sun.shadow.bias = -0.0007;
      scene.add(sun);

      // Grassland and a low-cost dirt approach.
      const ground = mesh(new THREE.CircleGeometry(31, 64), materials.grass, [0, -0.05, 0], [-Math.PI / 2, 0, 0]);
      scene.add(ground);
      const path = mesh(new THREE.PlaneGeometry(3.3, 11), materials.dirt, [0, -0.025, 7], [-Math.PI / 2, 0, 0]);
      scene.add(path);

      // Sparse instanced grass clumps keep the environment lightweight.
      const grassBladeGeometry = new THREE.ConeGeometry(.055, .48, 3);
      grassBladeGeometry.translate(0, .24, 0);
      const grassClumps = new THREE.InstancedMesh(grassBladeGeometry, materials.leafLight, 250);
      const dummy = new THREE.Object3D();
      for (let i = 0; i < 250; i++) {
        const angle = Math.random() * Math.PI * 2;
        const radius = 5.7 + Math.random() * 21;
        dummy.position.set(Math.cos(angle) * radius, 0, Math.sin(angle) * radius);
        const scale = .55 + Math.random() * .75;
        dummy.scale.set(scale, scale, scale);
        dummy.rotation.y = Math.random() * Math.PI;
        dummy.updateMatrix();
        grassClumps.setMatrixAt(i, dummy.matrix);
      }
      grassClumps.receiveShadow = true;
      scene.add(grassClumps);

      // Simple tree silhouettes and field fence add farm context without external models.
      function createTree(x, z, scale = 1) {
        const tree = new THREE.Group();
        tree.add(mesh(new THREE.CylinderGeometry(.18, .28, 2.3, 7), materials.woodDark, [0, 1.15, 0]));
        tree.add(mesh(new THREE.ConeGeometry(1.18, 2.3, 7), materials.leaf, [0, 2.65, 0]));
        tree.add(mesh(new THREE.ConeGeometry(.92, 1.8, 7), materials.leafLight, [.3, 3.45, -.05]));
        tree.position.set(x, 0, z);
        tree.scale.setScalar(scale);
        scene.add(tree);
      }
      createTree(-10, -8, 1.15);
      createTree(10, -10, .85);
      createTree(-14, 5, .75);

      const fence = new THREE.Group();
      for (let i = 0; i < 8; i++) {
        fence.add(mesh(new THREE.CylinderGeometry(.07, .09, 1.15, 6), materials.woodDark, [-12 + i * 3.4, .55, -12]));
      }
      for (const y of [.38, .82]) {
        fence.add(mesh(new THREE.CylinderGeometry(.045, .045, 23.8, 6), materials.woodDark, [-.1, y, -12], [0, 0, Math.PI / 2]));
      }
      scene.add(fence);

      const barn = new THREE.Group();
      barn.position.y = .04;
      scene.add(barn);

      // Original 5 x 4 elevated floor, borders, and plank spacing.
      barn.add(mesh(new THREE.BoxGeometry(5, .3, 4), materials.wood, [0, .25, 0]));
      const floorBorders = [
        [new THREE.BoxGeometry(5.2, .35, .15), [0, .25, -2]],
        [new THREE.BoxGeometry(5.2, .35, .15), [0, .25, 2]],
        [new THREE.BoxGeometry(.15, .35, 4), [-2.5, .25, 0]],
        [new THREE.BoxGeometry(.15, .35, 4), [2.5, .25, 0]]
      ];
      floorBorders.forEach(([geometry, position]) => barn.add(mesh(geometry, materials.woodDark, position)));
      for (let i = 0; i < 8; i++) {
        barn.add(mesh(new THREE.BoxGeometry(5.1, .32, .045), materials.woodDark, [0, .25, -1.8 + i * .5]));
      }

      // Original raised rear platform and central access ramp.
      const platformHeight = .8;
      barn.add(mesh(new THREE.BoxGeometry(5, .3, 2), materials.wood, [0, .25 + platformHeight, -1]));
      for (let i = 0; i < 4; i++) {
        barn.add(mesh(new THREE.BoxGeometry(5.1, .32, .045), materials.woodDark, [0, .25 + platformHeight, -1.8 + i * .5]));
      }
      barn.add(mesh(new THREE.BoxGeometry(5.2, .35, .15), materials.woodDark, [0, .25 + platformHeight, -2]));
      barn.add(mesh(new THREE.BoxGeometry(.15, .35, 2), materials.woodDark, [-2.5, .25 + platformHeight, -1]));
      barn.add(mesh(new THREE.BoxGeometry(.15, .35, 2), materials.woodDark, [2.5, .25 + platformHeight, -1]));
      [[-2, -1.8], [2, -1.8], [-2, -.2], [2, -.2]].forEach(([x, z]) => {
        barn.add(mesh(new THREE.BoxGeometry(.15, platformHeight, .15), materials.woodDark, [x, .25 + platformHeight / 2, z]));
      });
      const rampWidth = 1.5;
      const rampLength = 2;
      const rampAngle = Math.atan(platformHeight / rampLength);
      barn.add(mesh(new THREE.BoxGeometry(rampWidth, .15, rampLength), materials.wood, [0, .25 + platformHeight / 2, -.1], [rampAngle, 0, 0]));
      for (let i = 0; i < 5; i++) {
        const cleatZ = .8 - i * .4;
        const cleatY = .25 + platformHeight * (i * .4) / rampLength;
        barn.add(mesh(new THREE.BoxGeometry(rampWidth, .08, .08), materials.woodDark, [0, cleatY, cleatZ], [rampAngle, 0, 0]));
      }
      barn.add(mesh(new THREE.BoxGeometry(.08, .08, rampLength), materials.woodDark, [-rampWidth / 2 - .05, .25 + platformHeight / 2, -.1], [rampAngle, 0, 0]));
      barn.add(mesh(new THREE.BoxGeometry(.08, .08, rampLength), materials.woodDark, [rampWidth / 2 + .05, .25 + platformHeight / 2, -.1], [rampAngle, 0, 0]));

      // Exact original bamboo-panel language: narrow poles with three horizontal ties.
      function createBambooPanel(width, height) {
        const panel = new THREE.Group();
        const spacing = .12;
        const numberOfPoles = Math.floor(width / spacing);
        for (let i = 0; i < numberOfPoles; i++) {
          const pole = mesh(new THREE.CylinderGeometry(.04, .04, height, 8), materials.bamboo, [(i - numberOfPoles / 2) * spacing + spacing / 2, height / 2, 0]);
          panel.add(pole);
        }
        [height * .25, height * .5, height * .75].forEach(y => {
          panel.add(mesh(new THREE.CylinderGeometry(.025, .025, width, 8), materials.bambooDark, [0, y, 0], [0, 0, Math.PI / 2]));
        });
        return panel;
      }

      const backWall = createBambooPanel(5, 2.5);
      backWall.position.set(0, .2, -2);
      barn.add(backWall);
      const leftWall = createBambooPanel(4, 2.5);
      leftWall.rotation.y = Math.PI / 2;
      leftWall.position.set(-2.5, .2, 0);
      barn.add(leftWall);
      const rightWall = createBambooPanel(4, 2.5);
      rightWall.rotation.y = -Math.PI / 2;
      rightWall.position.set(2.5, .2, 0);
      barn.add(rightWall);
      const frontLeftWall = createBambooPanel(1.5, 3.2);
      frontLeftWall.position.set(-1.75, .25, 2);
      barn.add(frontLeftWall);
      const frontRightWall = createBambooPanel(1.5, 3.2);
      frontRightWall.position.set(1.75, .25, 2);
      barn.add(frontRightWall);

      // Restored original framed, half-open plank door.
      barn.add(mesh(new THREE.BoxGeometry(.12, 2.2, .12), materials.woodDark, [-.9, 1.35, 2.05]));
      barn.add(mesh(new THREE.BoxGeometry(.12, 2.2, .12), materials.woodDark, [.9, 1.35, 2.05]));
      barn.add(mesh(new THREE.BoxGeometry(2, .15, .15), materials.woodDark, [0, 2.45, 2.05]));
      const doorPanel = new THREE.Group();
      doorPanel.add(mesh(new THREE.BoxGeometry(.85, 2.1, .08), materials.wood, [0, 0, 0]));
      for (let i = 0; i < 5; i++) {
        doorPanel.add(mesh(new THREE.BoxGeometry(.87, .08, .09), materials.woodDark, [0, -.8 + i * .4, 0]));
      }
      doorPanel.add(mesh(new THREE.BoxGeometry(.08, .25, .08), materials.black, [.35, 0, .05]));
      doorPanel.position.set(-.5, 1.3, 2.1);
      doorPanel.rotation.y = -Math.PI / 6;
      barn.add(doorPanel);
      const aboveDoorWall = createBambooPanel(2.5, .65);
      aboveDoorWall.position.set(0, 2.75, 2);
      barn.add(aboveDoorWall);

      // Original single-slope corrugated roof, supports, and beams.
      const roofWidth = 6;
      const roofDepth = 5.2;
      const roofBackHeight = 3.5;
      const roofFrontHeight = 2.5;
      const roofAngle = -Math.atan((roofBackHeight - roofFrontHeight) / roofDepth);
      barn.add(mesh(new THREE.BoxGeometry(roofWidth, .05, roofDepth), materials.metal, [0, (roofBackHeight + roofFrontHeight) / 2, 0], [roofAngle, 0, 0]));
      for (let i = 0; i < 12; i++) {
        const x = -roofWidth / 2 + .25 + i * ((roofWidth - .5) / 11);
        barn.add(mesh(new THREE.BoxGeometry(.08, .025, roofDepth), materials.metalDark, [x, (roofBackHeight + roofFrontHeight) / 2 + .04, 0], [roofAngle, 0, 0]));
      }
      const mainPosts = [[-2.4, 1.35, -2, 2.8], [2.4, 1.35, -2, 2.8], [-2.4, 1.1, 2, 2.3], [2.4, 1.1, 2, 2.3]];
      mainPosts.forEach(([x, y, z, height]) => barn.add(mesh(new THREE.CylinderGeometry(.09, .1, height, 6), materials.woodDark, [x, y, z])));
      barn.add(mesh(new THREE.BoxGeometry(5.2, .12, .12), materials.woodDark, [0, 2.3, 2]));
      barn.add(mesh(new THREE.BoxGeometry(5.2, .12, .12), materials.woodDark, [0, 2.7, -2]));

      // Blue protective electronics enclosure mounted high on the rear wall.
      const enclosure = new THREE.Group();
      enclosure.position.set(1.42, 2.31, -1.78);
      enclosure.scale.setScalar(.74);
      enclosure.add(mesh(new THREE.BoxGeometry(2.05, 1.32, .52), materials.blueDark, [0, 0, 0]));
      enclosure.add(mesh(new THREE.BoxGeometry(1.88, 1.16, .12), materials.blue, [0, 0, .31]));
      enclosure.add(mesh(new THREE.BoxGeometry(1.72, .045, .025), new THREE.MeshStandardMaterial({ color: 0x58b8ef, emissive: 0x123d58, emissiveIntensity: .25 }), [0, .45, .382], null, false));
      for (const x of [-.76, .76]) {
        for (const y of [-.43, .43]) enclosure.add(mesh(new THREE.CylinderGeometry(.045, .045, .045, 10), materials.black, [x, y, .39], [Math.PI / 2, 0, 0]));
      }
      enclosure.add(mesh(new THREE.BoxGeometry(.16, .32, .07), materials.black, [.68, 0, .405], null, false));
      const statusLedMaterial = new THREE.MeshStandardMaterial({ color: 0xaeea63, emissive: 0x78d637, emissiveIntensity: 1.5 });
      enclosure.add(mesh(new THREE.SphereGeometry(.045, 10, 7), statusLedMaterial, [-.72, -.4, .39], null, false));
      const label = canvasTexture((ctx, w, h) => {
        ctx.fillStyle = '#eef7fb';
        ctx.fillRect(0, 0, w, h);
        ctx.fillStyle = '#12354d';
        ctx.font = 'bold 54px Arial';
        ctx.textAlign = 'center';
        ctx.fillText('CONTROL', w / 2, 82);
        ctx.font = '28px Arial';
        ctx.fillText('POWER • ESP32 • PI • RELAY', w / 2, 137);
      }, 512, 180);
      enclosure.add(mesh(new THREE.PlaneGeometry(1.17, .41), new THREE.MeshBasicMaterial({ map: label }), [-.12, -.08, .377], null, false));
      // Wall brackets communicate that the enclosure is securely mounted.
      enclosure.add(mesh(new THREE.BoxGeometry(2.28, .08, .14), materials.metalDark, [0, .76, -.12]));
      enclosure.add(mesh(new THREE.BoxGeometry(2.28, .08, .14), materials.metalDark, [0, -.76, -.12]));
      barn.add(enclosure);

      // Compact gravity auto-feeder: dispenser bottle, bottom outlet, and three-leg stand.
      const feeder = new THREE.Group();
      feeder.position.set(1.18, .4, .72);
      for (let i = 0; i < 3; i++) {
        const angle = i * Math.PI * 2 / 3 + Math.PI / 6;
        const x = Math.cos(angle) * .32;
        const z = Math.sin(angle) * .32;
        const leg = mesh(new THREE.CylinderGeometry(.055, .085, .72, 8), materials.metalDark, [x, .37, z]);
        leg.rotation.z = Math.cos(angle) * .13;
        leg.rotation.x = -Math.sin(angle) * .13;
        feeder.add(leg);
        feeder.add(mesh(new THREE.CylinderGeometry(.095, .095, .045, 10), materials.black, [x * 1.12, .025, z * 1.12]));
      }
      feeder.add(mesh(new THREE.TorusGeometry(.36, .04, 7, 20), materials.metalDark, [0, .72, 0], [Math.PI / 2, 0, 0]));

      // The shallow receiving tray sits below the visible gravity outlet.
      feeder.add(mesh(new THREE.CylinderGeometry(.46, .39, .1, 24), materials.feeder, [0, .62, 0]));
      feeder.add(mesh(new THREE.TorusGeometry(.43, .045, 7, 24), materials.feederEdge, [0, .68, 0], [Math.PI / 2, 0, 0]));
      feeder.add(mesh(new THREE.CylinderGeometry(.14, .21, .28, 12), materials.black, [0, .83, 0]));
      feeder.add(mesh(new THREE.ConeGeometry(.13, .22, 12), materials.feed, [0, .7, 0], [Math.PI, 0, 0]));

      // Water-dispenser-style vertical hopper; translucent shell reveals stored feed.
      const hopperProfile = [
        new THREE.Vector2(.14, 0),
        new THREE.Vector2(.15, .13),
        new THREE.Vector2(.29, .23),
        new THREE.Vector2(.36, .36),
        new THREE.Vector2(.36, .82),
        new THREE.Vector2(.31, 1.00),
        new THREE.Vector2(.18, 1.10),
        new THREE.Vector2(.03, 1.13)
      ];
      feeder.add(mesh(new THREE.CylinderGeometry(.265, .25, .66, 18), materials.feed, [0, 1.52, 0], null, false));
      const hopperMaterial = new THREE.MeshPhysicalMaterial({
        color: 0xb9dfec,
        transparent: true,
        opacity: .58,
        roughness: .18,
        metalness: 0,
        clearcoat: .65,
        clearcoatRoughness: .18,
        side: THREE.DoubleSide,
        depthWrite: false
      });
      feeder.add(mesh(new THREE.LatheGeometry(hopperProfile, 24), hopperMaterial, [0, .95, 0]));
      feeder.add(mesh(new THREE.TorusGeometry(.155, .026, 7, 18), materials.blueDark, [0, 1.07, 0], [Math.PI / 2, 0, 0]));
      barn.add(feeder);

      // Lightweight procedural goats used only as natural visual scenery.
      const goatMaterials = {
        white: new THREE.MeshStandardMaterial({ color: 0xe7dfcc, roughness: .92 }),
        cream: new THREE.MeshStandardMaterial({ color: 0xcbb993, roughness: .94 }),
        brown: new THREE.MeshStandardMaterial({ color: 0x8d6547, roughness: .95 }),
        dark: new THREE.MeshStandardMaterial({ color: 0x4d3b31, roughness: .95 }),
        marking: new THREE.MeshStandardMaterial({ color: 0x5b493c, roughness: .94 }),
        undercoat: new THREE.MeshStandardMaterial({ color: 0xb9a78a, roughness: .98 }),
        horn: new THREE.MeshStandardMaterial({ color: 0xb7a37b, roughness: .78 }),
        nose: new THREE.MeshStandardMaterial({ color: 0x6e554d, roughness: .72 }),
        hoof: new THREE.MeshStandardMaterial({ color: 0x242321, roughness: .82 }),
        eye: new THREE.MeshStandardMaterial({ color: 0x101312, roughness: .3 }),
        eyeGlint: new THREE.MeshBasicMaterial({ color: 0xf7f3e8 })
      };

      function goatSegment(start, end, startRadius, endRadius, material, radialSegments = 7) {
        const from = new THREE.Vector3(...start);
        const to = new THREE.Vector3(...end);
        const direction = to.clone().sub(from);
        const segment = mesh(
          new THREE.CylinderGeometry(endRadius, startRadius, direction.length(), radialSegments),
          material,
          null,
          null
        );
        segment.position.copy(from).add(to).multiplyScalar(.5);
        segment.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction.normalize());
        return segment;
      }

      function createGoat(config) {
        const goat = new THREE.Group();

        const coat = goatMaterials[config.coat] || goatMaterials.white;
        const isResting = config.pose === 'resting';
        const isHeadDown = config.pose === 'feeding' || config.pose === 'grazing';
        const isWalking = config.pose === 'walking';
        const bodyY = isResting ? .41 : .75;
        const headY = isResting ? .48 : (isHeadDown ? .55 : .98);
        const headZ = isResting ? .7 : (isHeadDown ? .9 : .72);

        const body = mesh(new THREE.SphereGeometry(.5, 11, 7), coat, [0, bodyY, 0]);
        body.scale.set(.58, isResting ? .46 : .54, 1.14);
        goat.add(body);
        const chest = mesh(new THREE.SphereGeometry(.38, 10, 7), coat, [0, bodyY + .03, .35]);
        chest.scale.set(.72, isResting ? .63 : .88, .92);
        goat.add(chest);
        const hip = mesh(new THREE.SphereGeometry(.36, 10, 7), coat, [0, bodyY + .035, -.34]);
        hip.scale.set(.74, isResting ? .62 : .8, .8);
        goat.add(hip);
        const belly = mesh(new THREE.SphereGeometry(.32, 9, 6), goatMaterials.undercoat, [0, bodyY - .2, -.03]);
        belly.scale.set(.72, .38, 1.18);
        goat.add(belly);
        const shoulderPatch = mesh(new THREE.SphereGeometry(.37, 9, 6), config.marked ? goatMaterials.marking : coat, [0, bodyY + .03, .25]);
        shoulderPatch.scale.set(.66, .64, .72);
        goat.add(shoulderPatch);

        if (isResting) {
          for (const x of [-.3, .3]) {
            for (const z of [-.28, .28]) {
              const foldedLeg = mesh(new THREE.CylinderGeometry(.052, .067, .3, 7), coat, [x, .18, z], [0, 0, Math.PI / 2]);
              goat.add(foldedLeg);
              for (const split of [-1, 1]) {
                goat.add(mesh(new THREE.BoxGeometry(.04, .065, .1), goatMaterials.hoof, [x + split * .026, .105, z + .09]));
              }
            }
          }
        } else {
          for (const x of [-.28, .28]) {
            for (const z of [-.34, .34]) {
              const stride = isWalking ? (x * z > 0 ? .2 : -.2) : 0;
              const upperLeg = mesh(new THREE.CylinderGeometry(.055, .072, .3, 7), coat, [x, .42, z]);
              upperLeg.rotation.x = stride;
              goat.add(upperLeg);
              const kneeZ = z + stride * .13;
              const footZ = z + stride * .36;
              goat.add(mesh(new THREE.SphereGeometry(.075, 7, 5), coat, [x, .275, kneeZ]));
              const lowerLeg = mesh(new THREE.CylinderGeometry(.04, .055, .28, 7), goatMaterials.undercoat, [x, .16, (kneeZ + footZ) / 2]);
              lowerLeg.rotation.x = stride * .7;
              goat.add(lowerLeg);
              for (const split of [-1, 1]) {
                goat.add(mesh(new THREE.BoxGeometry(.043, .08, .115), goatMaterials.hoof, [x + split * .028, .045, footZ]));
              }
            }
          }
        }

        const neckStart = [0, bodyY + .04, .34];
        const neckEnd = [0, headY - .12, headZ - .15];
        goat.add(goatSegment(neckStart, neckEnd, .2, .13, coat, 9));
        const throat = goatSegment([0, bodyY - .03, .4], [0, headY - .21, headZ - .08], .11, .075, goatMaterials.undercoat, 8);
        goat.add(throat);

        const head = mesh(new THREE.SphereGeometry(.25, 10, 7), coat, [0, headY, headZ]);
        head.scale.set(.7, 1.03, 1.16);
        goat.add(head);
        const faceBridge = mesh(new THREE.SphereGeometry(.17, 9, 6), coat, [0, headY - .015, headZ + .2]);
        faceBridge.scale.set(.7, .83, 1.22);
        goat.add(faceBridge);
        const brow = mesh(new THREE.SphereGeometry(.18, 9, 6), coat, [0, headY + .09, headZ + .09]);
        brow.scale.set(.9, .62, .9);
        goat.add(brow);
        const muzzle = mesh(new THREE.SphereGeometry(.15, 9, 6), goatMaterials.nose, [0, headY - .09, headZ + .36]);
        muzzle.scale.set(.76, .58, .78);
        goat.add(muzzle);
        for (const side of [-1, 1]) {
          goat.add(mesh(new THREE.SphereGeometry(.016, 6, 4), goatMaterials.eye, [side * .05, headY - .1, headZ + .465], null, false));
        }

        const beard = mesh(new THREE.ConeGeometry(.105, .42, 7), goatMaterials.undercoat, [0, headY - .34, headZ + .14]);
        beard.rotation.x = -.18;
        beard.scale.set(.8, 1, .58);
        goat.add(beard);

        for (const side of [-1, 1]) {
          const ear = mesh(new THREE.SphereGeometry(.24, 8, 5), coat, [side * .25, headY + .075, headZ - .015]);
          ear.scale.set(.88, .18, .34);
          ear.rotation.z = side * -.12;
          ear.rotation.y = side * .16;
          goat.add(ear);
          const hornRoot = [side * .1, headY + .2, headZ - .1];
          const hornMid = [side * .12, headY + .43, headZ - .19];
          const hornEnd = [side * .13, headY + .57, headZ - .38];
          goat.add(goatSegment(hornRoot, hornMid, .065, .045, goatMaterials.horn));
          goat.add(goatSegment(hornMid, hornEnd, .045, .012, goatMaterials.horn));
          goat.add(mesh(new THREE.SphereGeometry(.029, 7, 5), goatMaterials.eye, [side * .15, headY + .055, headZ + .22], null, false));
          goat.add(mesh(new THREE.SphereGeometry(.008, 5, 3), goatMaterials.eyeGlint, [side * .159, headY + .066, headZ + .245], null, false));
        }

        goat.add(goatSegment([0, bodyY + .14, -.48], [0, bodyY + .4, -.72], .075, .035, coat));
        const tailTip = mesh(new THREE.ConeGeometry(.04, .18, 7), coat, [0, bodyY + .46, -.78]);
        tailTip.rotation.x = -.62;
        goat.add(tailTip);

        goat.position.set(...config.position);
        goat.rotation.y = config.rotation;
        goat.scale.setScalar(config.scale || 1);
        return goat;
      }

      const goatsGroup = new THREE.Group();
      scene.add(goatsGroup);
      [
        { pose: 'feeding', coat: 'white', marked: true, position: [1.62, .44, 1.33], rotation: -2.55, scale: .86 },
        { pose: 'resting', coat: 'brown', marked: false, position: [-1.35, 1.24, -1.18], rotation: .72, scale: .9 },
        { pose: 'standing', coat: 'cream', marked: true, position: [-.66, .44, 1.28], rotation: .08, scale: .88 },
        { pose: 'walking', coat: 'dark', marked: true, position: [-3.45, 0, 3.35], rotation: -1.08, scale: .94 }
      ].forEach(config => {
        goatsGroup.add(createGoat(config));
      });

      // Real in-scene light: fixture, emissive bulb, glow sprite, and shadow-casting point light.
      barn.add(mesh(new THREE.CylinderGeometry(.025, .025, .38, 8), materials.black, [0, 2.83, -.1]));
      barn.add(mesh(new THREE.CylinderGeometry(.28, .42, .22, 20, 1, true), materials.metalDark, [0, 2.58, -.1]));
      const bulbMaterial = new THREE.MeshStandardMaterial({ color: 0xfff1bf, emissive: 0xffb632, emissiveIntensity: 2.8, roughness: .2 });
      const bulb = mesh(new THREE.SphereGeometry(.15, 16, 10), bulbMaterial, [0, 2.43, -.1], null, false);
      barn.add(bulb);
      const interiorLight = new THREE.PointLight(0xffbe62, 3.6, 10, 1.7);
      interiorLight.position.set(0, 2.29, -.1);
      interiorLight.castShadow = true;
      interiorLight.shadow.mapSize.set(512, 512);
      interiorLight.shadow.bias = -0.001;
      barn.add(interiorLight);

      const glowTexture = canvasTexture((ctx, w, h) => {
        const g = ctx.createRadialGradient(w / 2, h / 2, 1, w / 2, h / 2, w / 2);
        g.addColorStop(0, 'rgba(255,244,191,.9)');
        g.addColorStop(.25, 'rgba(255,202,91,.38)');
        g.addColorStop(1, 'rgba(255,187,69,0)');
        ctx.fillStyle = g;
        ctx.fillRect(0, 0, w, h);
      }, 128, 128);
      const glowMaterial = new THREE.SpriteMaterial({ map: glowTexture, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
      const bulbGlow = new THREE.Sprite(glowMaterial);
      bulbGlow.position.set(0, 2.43, -.1);
      bulbGlow.scale.set(1.85, 1.85, 1);
      barn.add(bulbGlow);

      // Compact manual orbit controls avoid another runtime dependency.
      const target = new THREE.Vector3(0, 1.55, 0);
      let spherical = new THREE.Spherical().setFromVector3(camera.position.clone().sub(target));
      let dragging = false;
      let panning = false;
      let previousX = 0;
      let previousY = 0;
      let targetSpherical = spherical.clone();
      let targetLookAt = target.clone();

      function syncCamera() {
        spherical.radius += (targetSpherical.radius - spherical.radius) * .12;
        spherical.phi += (targetSpherical.phi - spherical.phi) * .12;
        spherical.theta += (targetSpherical.theta - spherical.theta) * .12;
        target.lerp(targetLookAt, .12);
        camera.position.copy(new THREE.Vector3().setFromSpherical(spherical).add(target));
        camera.lookAt(target);
      }

      function invalidate() {
        dirtyFrames = 90;
        if (initialized && !destroyed && inViewport && !document.hidden && animationFrameId === null) animate();
      }

      renderer.domElement.addEventListener('contextmenu', event => event.preventDefault());
      renderer.domElement.addEventListener('pointerdown', event => {
        dragging = true;
        panning = event.button === 2 || event.shiftKey;
        previousX = event.clientX;
        previousY = event.clientY;
        renderer.domElement.setPointerCapture(event.pointerId);
      });
      renderer.domElement.addEventListener('pointermove', event => {
        if (!dragging) return;
        const dx = event.clientX - previousX;
        const dy = event.clientY - previousY;
        previousX = event.clientX;
        previousY = event.clientY;
        if (panning) {
          const right = new THREE.Vector3().setFromMatrixColumn(camera.matrix, 0);
          const up = new THREE.Vector3(0, 1, 0);
          targetLookAt.addScaledVector(right, -dx * .009).addScaledVector(up, dy * .009);
        } else {
          targetSpherical.theta -= dx * .006;
          targetSpherical.phi = THREE.MathUtils.clamp(targetSpherical.phi - dy * .006, .3, 1.46);
        }
        setActiveView('');
        invalidate();
      });
      renderer.domElement.addEventListener('pointerup', event => {
        dragging = false;
        renderer.domElement.releasePointerCapture(event.pointerId);
      });
      renderer.domElement.addEventListener('wheel', event => {
        event.preventDefault();
        targetSpherical.radius = THREE.MathUtils.clamp(targetSpherical.radius + event.deltaY * .012, 7.5, 27);
        setActiveView('');
        invalidate();
      }, { passive: false });

      const views = {
        review: { position: [8.6, 5.4, 10.2], target: [0, 1.55, 0] },
        front: { position: [0, 3.7, 11.4], target: [0, 1.55, 0] },
        side: { position: [11.4, 3.8, .8], target: [0, 1.6, 0] },
        top: { position: [7.2, 11.2, 8.1], target: [0, 1.25, 0] }
      };

      const viewButtons = Array.from(container.querySelectorAll('[data-view]'));
      function setActiveView(name) {
        viewButtons.forEach(button => button.classList.toggle('active', button.dataset.view === name));
      }

      const viewBindings = viewButtons.map(button => {
        const handler = () => {
          const view = views[button.dataset.view];
          if (!view) return;
          targetLookAt.set(...view.target);
          const offset = new THREE.Vector3(...view.position).sub(targetLookAt);
          targetSpherical = new THREE.Spherical().setFromVector3(offset);
          setActiveView(button.dataset.view);
          invalidate();
        };
        button.addEventListener('click', handler);
        return [button, handler];
      });

      function updateInteriorLight(isOn) {
        isOn = Boolean(isOn);
        interiorLight.intensity = isOn ? 3.6 : 0;
        bulbMaterial.emissiveIntensity = isOn ? 2.8 : 0;
        bulbMaterial.color.setHex(isOn ? 0xfff1bf : 0x6c726e);
        bulbGlow.visible = isOn;
        container.dataset.lightState = isOn ? 'on' : 'off';
        invalidate();
      }

      function updateEnvironment(isDay) {
        const skyColor = isDay ? 0x9bc6dc : 0x071321;
        scene.background.setHex(skyColor);
        scene.fog.color.setHex(skyColor);
        scene.fog.near = isDay ? 30 : 21;
        scene.fog.far = isDay ? 66 : 48;

        hemisphere.color.setHex(isDay ? 0xdff3ff : 0x243754);
        hemisphere.groundColor.setHex(isDay ? 0x38502d : 0x08140f);
        hemisphere.intensity = isDay ? 1.03 : .17;
        sun.color.setHex(isDay ? 0xfff1d1 : 0x7890bd);
        sun.intensity = isDay ? 2.05 : .12;

        materials.grass.color.setHex(isDay ? 0xa8d081 : 0x243a2d);
        materials.leaf.color.setHex(isDay ? 0x426f38 : 0x14271d);
        materials.leafLight.color.setHex(isDay ? 0x66944a : 0x203a28);
        materials.dirt.color.setHex(isDay ? 0x8a6747 : 0x352c28);
        renderer.toneMappingExposure = isDay ? 1.05 : .68;

        container.dataset.environment = isDay ? 'day' : 'night';
        const environmentState = container.querySelector('[data-environment-state]');
        if (environmentState) environmentState.textContent = isDay ? 'Day · Manila time' : 'Night · Manila time';
      }

      function isManilaDaytime() {
        const parts = new Intl.DateTimeFormat('en-US', {
          timeZone: 'Asia/Manila',
          hour: '2-digit',
          hourCycle: 'h23'
        }).formatToParts(new Date());
        const hourPart = parts.find(part => part.type === 'hour');
        const hour = hourPart ? Number(hourPart.value) : 12;
        return hour >= 6 && hour < 18;
      }

      function refreshEnvironment() {
        if (document.hidden || !inViewport) return;
        updateEnvironment(isManilaDaytime());
        invalidate();
      }

      function onSystemLightState(event) {
        const detail = event.detail || {};
        updateInteriorLight(detail.isOn !== undefined ? detail.isOn : detail.state === 'on');
      }
      window.addEventListener('gohmotech:light-state', onSystemLightState);
      refreshEnvironment();
      updateInteriorLight(initialLightOn);
      const environmentTimer = window.setInterval(refreshEnvironment, 60000);

      function resize() {
        if (destroyed) return;
        const width = Math.max(container.clientWidth, 1);
        const height = Math.max(container.clientHeight, 1);
        camera.aspect = width / height;
        camera.updateProjectionMatrix();
        renderer.setPixelRatio(Math.min(devicePixelRatio, mobile ? 1 : 1.75));
        renderer.setSize(width, height, false);
        invalidate();
      }
      const resizeObserver = window.ResizeObserver ? new ResizeObserver(resize) : null;
      if (resizeObserver) resizeObserver.observe(container);
      else window.addEventListener('resize', resize);

      let firstFrame = true;
      function animate() {
        animationFrameId = null;
        if (destroyed || document.hidden || !inViewport) return;
        syncCamera();
        renderer.render(scene, camera);
        if (firstFrame) {
          firstFrame = false;
          if (loading) loading.hidden = true;
        }
        if (--dirtyFrames > 0) animationFrameId = requestAnimationFrame(animate);
      }
      const visibilityObserver = window.IntersectionObserver ? new IntersectionObserver(entries => {
        inViewport = entries[0].isIntersecting;
        if (inViewport) invalidate();
      }) : null;
      if (visibilityObserver) visibilityObserver.observe(container);
      document.addEventListener('visibilitychange', invalidate);
      initialized = true;
      invalidate();

      function destroy() {
        if (destroyed) return;
        destroyed = true;
        if (animationFrameId !== null) cancelAnimationFrame(animationFrameId);
        window.clearInterval(environmentTimer);
        if (visibilityObserver) visibilityObserver.disconnect();
        document.removeEventListener('visibilitychange', invalidate);
        window.removeEventListener('gohmotech:light-state', onSystemLightState);
        if (resizeObserver) resizeObserver.disconnect();
        else window.removeEventListener('resize', resize);
        viewBindings.forEach(([button, handler]) => button.removeEventListener('click', handler));
        scene.traverse(object => {
          if (object.geometry && object.geometry.dispose) object.geometry.dispose();
          const objectMaterials = object.material ? (Array.isArray(object.material) ? object.material : [object.material]) : [];
          objectMaterials.forEach(material => {
            Object.keys(material).forEach(key => {
              const value = material[key];
              if (value && value.isTexture && value.dispose) value.dispose();
            });
            if (material.dispose) material.dispose();
          });
        });
        renderer.dispose();
        if (renderer.forceContextLoss) renderer.forceContextLoss();
        if (renderer.domElement.parentNode === container) container.removeChild(renderer.domElement);
      }

      return { destroy, setLightState: updateInteriorLight, refreshEnvironment };

  }

  window.createApprovedGoatHouseViewer = createApprovedGoatHouseViewer;
})(window, document);
