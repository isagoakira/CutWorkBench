/* Local CEP host bridge. Animated and unsupported AE properties remain opaque. */
$.global.CutWorkbenchAfterEffects = (function () {
    var ADAPTER_ID = "after-effects:cep-local", PROTOCOL_VERSION = 1;
    function parse(argument) { return JSON.parse(argument); }
    function normal(path) { return String(path || "").replace(/\\/g, "/").toLowerCase(); }
    function requireRoot(config) { if (!config || !config.root) { throw new Error("Bridge directory is required."); } var root = new Folder(config.root); if (!root.exists && !root.create()) { throw new Error("Cannot create bridge directory."); } return root; }
    function writeJson(file, value) { var temporary = new File(file.fsName + ".tmp-" + new Date().getTime()); temporary.encoding = "UTF-8"; if (!temporary.open("w")) { throw new Error("Cannot write " + temporary.fsName); } temporary.write(JSON.stringify(value)); temporary.close(); if (file.exists && !file.remove()) { temporary.remove(); throw new Error("Cannot replace " + file.fsName); } if (!temporary.rename(file.name)) { temporary.remove(); throw new Error("Cannot finalize " + file.fsName); } }
    function readJson(file) { file.encoding = "UTF-8"; if (!file.open("r")) { throw new Error("Cannot read " + file.fsName); } var text = file.read(); file.close(); return JSON.parse(text); }
    function fnv(value) { var hash = 2166136261, i; for (i = 0; i < value.length; i++) { hash ^= value.charCodeAt(i); hash += (hash << 1) + (hash << 4) + (hash << 7) + (hash << 8) + (hash << 24); } return "fnv1a32:" + (hash >>> 0).toString(16); }
    function composition() { if (!(app.project && app.project.activeItem && app.project.activeItem instanceof CompItem)) { throw new Error("Open an active After Effects composition first."); } return app.project.activeItem; }
    function isStatic(property) { return property.numKeys === 0 && !property.expressionEnabled; }
    function value(property) { return isStatic(property) ? property.value : null; }
    function transform(layer) {
        var group = layer.property("ADBE Transform Group"), position = group.property("ADBE Position"), scale = group.property("ADBE Scale"), rotation = group.property("ADBE Rotate Z"), opacity = group.property("ADBE Opacity");
        return { position: value(position), scale: value(scale), rotation: value(rotation), opacity: value(opacity), keyframed: position.numKeys + scale.numKeys + rotation.numKeys + opacity.numKeys > 0, expression_driven: !!(position.expressionEnabled || scale.expressionEnabled || rotation.expressionEnabled || opacity.expressionEnabled) };
    }
    function sourcePath(layer) { try { return layer.source && layer.source.file ? String(layer.source.file.fsName) : ""; } catch (ignored) { return ""; } }
    function snapshot() {
        var comp = composition(), projectPath = app.project.file ? String(app.project.file.fsName) : "", tracks = { layers: { external_id: "layers", kind: "video", order: 0 } }, materials = {}, entities = {}, signature = [projectPath, comp.id, comp.numLayers], i, layer, layerId, path, materialId, tr, writable;
        for (i = 1; i <= comp.numLayers; i++) {
            layer = comp.layer(i); layerId = String(layer.id); path = sourcePath(layer); materialId = layer.source ? String(layer.source.id) : "layer-" + layerId; tr = transform(layer); writable = !tr.keyframed && !tr.expression_driven;
            if (!materials[materialId]) { materials[materialId] = { external_id: materialId, kind: "media", path: path }; }
            entities[layerId] = { external_id: layerId, kind: "layer", track_external_id: "layers", material_external_id: materialId, properties: { transform: tr }, property_paths: writable ? { transform: "/comps/" + comp.id + "/layers/" + layerId + "/transform" } : {}, native: { layer_id: layerId, layer_index: i, layer_type: String(layer.matchName || "") } };
            signature.push(layerId, layer.startTime, layer.inPoint, layer.outPoint, JSON.stringify(tr));
        }
        return { schema_version: 1, adapter_id: ADAPTER_ID, draft_id: String(comp.id), fingerprint: fnv(signature.join("|")), tracks: tracks, materials: materials, entities: entities, native_summary: { active_path: projectPath, composition_id: String(comp.id), host: "After Effects" } };
    }
    function writeState(config) { var root = requireRoot(config), projectPath = app.project.file ? String(app.project.file.fsName) : "", state = snapshot(); writeJson(new File(root.fsName + "/profile.json"), { protocol_version: PROTOCOL_VERSION, adapter_id: ADAPTER_ID, editor_version: String(app.version), writable: true }); writeJson(new File(root.fsName + "/authorization.json"), { protocol_version: PROTOCOL_VERSION, adapter_id: ADAPTER_ID, publish_enabled: !!config.writable }); writeJson(new File(root.fsName + "/snapshot.json"), { protocol_version: PROTOCOL_VERSION, adapter_id: ADAPTER_ID, draft_path: projectPath, snapshot: state }); return state; }
    function layerMap() { var comp = composition(), result = {}, i; for (i = 1; i <= comp.numLayers; i++) { result[String(comp.layer(i).id)] = comp.layer(i); } return result; }
    function writableMap(state) { var result = {}, entityId, entity, path, pieces; for (entityId in state.entities) if (state.entities.hasOwnProperty(entityId)) { entity = state.entities[entityId]; if (entity.property_paths.transform) { path = entity.property_paths.transform; pieces = path.split("/"); result[path] = { layer_id: pieces[pieces.length - 2] }; } } return result; }
    function validateTransform(layer, next) { if (!next || typeof next !== "object") { throw new Error("Transform must be an object."); } var group = layer.property("ADBE Transform Group"), names = { position: "ADBE Position", scale: "ADBE Scale", rotation: "ADBE Rotate Z", opacity: "ADBE Opacity" }, key, property; for (key in next) if (next.hasOwnProperty(key) && key !== "keyframed" && key !== "expression_driven") { if (!names[key]) { throw new Error("Unsupported transform field: " + key); } property = group.property(names[key]); if (!property || !isStatic(property)) { throw new Error("Transform property is animated, expression-driven, or unsupported: " + key); } } }
    function validatePatches(command, state, map) { var allowed = writableMap(state), validated = [], i, patch, target; if (!command.patches || !(command.patches instanceof Array)) { throw new Error("Command patches must be an array."); } for (i = 0; i < command.patches.length; i++) { patch = command.patches[i]; target = patch ? allowed[patch.path] : null; if (!patch || patch.op !== "set" || !target || !map[target.layer_id]) { throw new Error("Patch is outside the After Effects allowlist."); } validateTransform(map[target.layer_id], patch.value); validated.push({ target: target, value: patch.value }); } return validated; }
    function setTransform(layer, next) {
        if (!next || typeof next !== "object") { throw new Error("Transform must be an object."); }
        var group = layer.property("ADBE Transform Group"), names = { position: "ADBE Position", scale: "ADBE Scale", rotation: "ADBE Rotate Z", opacity: "ADBE Opacity" }, key, property;
        validateTransform(layer, next);
        for (key in next) if (next.hasOwnProperty(key) && key !== "keyframed" && key !== "expression_driven") { property = group.property(names[key]); property.setValue(next[key]); }
    }
    function apply(command) {
        var current = snapshot(), destination = new File(command.destination_path), map, validated, i, layer;
        if (command.adapter_id !== ADAPTER_ID || command.kind !== "publish-clone") { throw new Error("Command targets another adapter."); }
        if (normal(command.source_path) !== normal(app.project.file.fsName) || command.expected_fingerprint !== current.fingerprint) { throw new Error("Project changed; refresh and preview again."); }
        if (destination.exists) { throw new Error("Destination project already exists."); }
        map = layerMap(); validated = validatePatches(command, current, map); app.project.save(destination); map = layerMap(); app.beginUndoGroup("Cut Workbench clone publish");
        try { for (i = 0; i < validated.length; i++) { layer = map[validated[i].target.layer_id]; if (!layer) { throw new Error("Cloned project no longer contains a validated layer."); } setTransform(layer, validated[i].value); } app.project.save(); }
        finally { app.endUndoGroup(); }
        return snapshot();
    }
    function publish(root, command) { var response = { protocol_version: PROTOCOL_VERSION, request_id: command.request_id, adapter_id: ADAPTER_ID, source_path: command.source_path, destination_path: command.destination_path, applied_patches: command.patches || [] }; try { var result = apply(command); response.status = "published"; response.source_fingerprint = command.expected_fingerprint; response.result_fingerprint = result.fingerprint; response.result_snapshot = result; } catch (error) { response.status = "rejected"; response.error = String(error); } writeJson(new File(root.fsName + "/responses/" + command.request_id + ".json"), response); }
    return { refresh: function (argument) { try { var state = writeState(parse(argument)); return "Snapshot " + state.fingerprint; } catch (error) { return "Error: " + error; } }, poll: function (argument) { try { var config = parse(argument), root = requireRoot(config), commands = new Folder(root.fsName + "/commands"), responses = new Folder(root.fsName + "/responses"), files, i, command; writeState(config); if (!config.writable) { return "Read-only snapshot updated."; } if (!commands.exists) { return "No commands."; } if (!responses.exists) { responses.create(); } files = commands.getFiles("*.json"); for (i = 0; i < files.length; i++) { command = readJson(files[i]); if (!new File(responses.fsName + "/" + command.request_id + ".json").exists) { publish(root, command); } } return "Checked " + files.length + " command(s)."; } catch (error) { return "Error: " + error; } } };
}());
