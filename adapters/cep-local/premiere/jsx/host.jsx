/* Local CEP host bridge. It accepts only its fixed JSON file protocol. */
$.global.CutWorkbenchPremiere = (function () {
    var ADAPTER_ID = "premiere:cep-local";
    var PROTOCOL_VERSION = 1;

    function parse(argument) { return JSON.parse(argument); }
    function normal(path) { return String(path || "").replace(/\\/g, "/").toLowerCase(); }
    function requireRoot(config) {
        if (!config || !config.root) { throw new Error("Bridge directory is required."); }
        var root = new Folder(config.root);
        if (!root.exists && !root.create()) { throw new Error("Cannot create bridge directory."); }
        return root;
    }
    function writeJson(file, value) {
        var temporary = new File(file.fsName + ".tmp-" + new Date().getTime());
        temporary.encoding = "UTF-8";
        if (!temporary.open("w")) { throw new Error("Cannot write " + temporary.fsName); }
        temporary.write(JSON.stringify(value)); temporary.close();
        if (file.exists && !file.remove()) { temporary.remove(); throw new Error("Cannot replace " + file.fsName); }
        if (!temporary.rename(file.name)) { temporary.remove(); throw new Error("Cannot finalize " + file.fsName); }
    }
    function readJson(file) {
        file.encoding = "UTF-8";
        if (!file.open("r")) { throw new Error("Cannot read " + file.fsName); }
        var text = file.read(); file.close(); return JSON.parse(text);
    }
    function fnv(value) {
        var hash = 2166136261, i;
        for (i = 0; i < value.length; i++) { hash ^= value.charCodeAt(i); hash += (hash << 1) + (hash << 4) + (hash << 7) + (hash << 8) + (hash << 24); }
        return "fnv1a32:" + (hash >>> 0).toString(16);
    }
    function mediaPath(item) {
        try { return item && item.getMediaPath ? String(item.getMediaPath() || "") : ""; } catch (ignored) { return ""; }
    }
    function sequence() {
        if (!app.project || !app.project.activeSequence) { throw new Error("Open an active Premiere sequence first."); }
        return app.project.activeSequence;
    }
    function snapshot() {
        var seq = sequence(), projectPath = String(app.project.path || ""), tracks = {}, materials = {}, entities = {}, signature = [projectPath, seq.sequenceID];
        function addTracks(collection, kind) {
            var i, j, track, clip, trackId, clipId, materialId, path, props;
            for (i = 0; i < collection.numTracks; i++) {
                track = collection[i]; trackId = kind + "-" + String(track.id || i);
                tracks[trackId] = { external_id: trackId, kind: kind, order: i };
                for (j = 0; j < track.clips.numItems; j++) {
                    clip = track.clips[j]; clipId = String(clip.nodeId); materialId = String(clip.projectItem ? clip.projectItem.nodeId : clipId);
                    path = mediaPath(clip.projectItem);
                    if (!materials[materialId]) { materials[materialId] = { external_id: materialId, kind: "media", path: path }; }
                    props = { timeline_start: clip.start.seconds, timeline_duration: clip.duration.seconds, source_in: clip.inPoint.seconds, source_out: clip.outPoint.seconds, speed: clip.getSpeed(), transform: {} };
                    entities[clipId] = {
                        external_id: clipId, kind: "segment", track_external_id: trackId, material_external_id: materialId,
                        properties: props,
                        property_paths: {
                            source_in: "/sequences/" + seq.sequenceID + "/" + kind + "/" + trackId + "/" + clipId + "/source_in",
                            source_out: "/sequences/" + seq.sequenceID + "/" + kind + "/" + trackId + "/" + clipId + "/source_out"
                        },
                        native: { node_id: clipId, project_item_node_id: materialId }
                    };
                    signature.push(trackId, clipId, clip.start.ticks, clip.inPoint.ticks, clip.outPoint.ticks, clip.getSpeed());
                }
            }
        }
        addTracks(seq.videoTracks, "video"); addTracks(seq.audioTracks, "audio");
        return { schema_version: 1, adapter_id: ADAPTER_ID, draft_id: String(seq.sequenceID), fingerprint: fnv(signature.join("|")), tracks: tracks, materials: materials, entities: entities, native_summary: { active_path: projectPath, sequence_id: String(seq.sequenceID), host: "Premiere Pro" } };
    }
    function writeState(config) {
        var root = requireRoot(config), projectPath = String(app.project.path || ""), state = snapshot();
        writeJson(new File(root.fsName + "/profile.json"), { protocol_version: PROTOCOL_VERSION, adapter_id: ADAPTER_ID, editor_version: String(app.version), writable: true });
        writeJson(new File(root.fsName + "/authorization.json"), { protocol_version: PROTOCOL_VERSION, adapter_id: ADAPTER_ID, publish_enabled: !!config.writable });
        writeJson(new File(root.fsName + "/snapshot.json"), { protocol_version: PROTOCOL_VERSION, adapter_id: ADAPTER_ID, draft_path: projectPath, snapshot: state });
        return state;
    }
    function clipMap() {
        var seq = sequence(), result = {}, groups = [seq.videoTracks, seq.audioTracks], i, j, group;
        for (group = 0; group < groups.length; group++) for (i = 0; i < groups[group].numTracks; i++) for (j = 0; j < groups[group][i].clips.numItems; j++) result[String(groups[group][i].clips[j].nodeId)] = groups[group][i].clips[j];
        return result;
    }
    function writableMap(state) {
        var result = {}, entityId, entity, field, path, pieces;
        for (entityId in state.entities) if (state.entities.hasOwnProperty(entityId)) {
            entity = state.entities[entityId];
            for (field in entity.property_paths) if (entity.property_paths.hasOwnProperty(field)) {
                path = entity.property_paths[field]; pieces = path.split("/");
                result[path] = { clip_id: pieces[pieces.length - 2], field: field, properties: entity.properties };
            }
        }
        return result;
    }
    function validatePatches(command, state) {
        var allowed = writableMap(state), ranges = {}, validated = [], i, patch, target, range;
        if (!command.patches || !(command.patches instanceof Array)) { throw new Error("Command patches must be an array."); }
        for (i = 0; i < command.patches.length; i++) {
            patch = command.patches[i]; target = patch ? allowed[patch.path] : null;
            if (!patch || patch.op !== "set" || !target || (target.field !== "source_in" && target.field !== "source_out") || typeof patch.value !== "number" || patch.value < 0) { throw new Error("Patch is outside the Premiere allowlist."); }
            range = ranges[target.clip_id] || { source_in: target.properties.source_in, source_out: target.properties.source_out }; range[target.field] = patch.value; ranges[target.clip_id] = range;
            validated.push({ target: target, value: patch.value });
        }
        for (i in ranges) if (ranges.hasOwnProperty(i) && ranges[i].source_out <= ranges[i].source_in) { throw new Error("Patch would create an invalid source range."); }
        return validated;
    }
    function setSeconds(clip, field, value) {
        if (typeof value !== "number" || value < 0) { throw new Error("Invalid source time."); }
        var time = new Time(); time.seconds = value;
        if (field === "source_in") { clip.inPoint = time; } else if (field === "source_out") { clip.outPoint = time; } else { throw new Error("Unsupported Premiere patch field."); }
    }
    function apply(command) {
        var current = snapshot(), destination = new File(command.destination_path), map, validated, i, clip;
        if (command.adapter_id !== ADAPTER_ID || command.kind !== "publish-clone") { throw new Error("Command targets another adapter."); }
        if (normal(command.source_path) !== normal(app.project.path) || command.expected_fingerprint !== current.fingerprint) { throw new Error("Project changed; refresh and preview again."); }
        if (destination.exists) { throw new Error("Destination project already exists."); }
        validated = validatePatches(command, current);
        if (!app.project.saveAs(command.destination_path)) { throw new Error("Premiere could not create the project clone."); }
        map = clipMap();
        for (i = 0; i < validated.length; i++) {
            clip = map[validated[i].target.clip_id];
            if (!clip) { throw new Error("Cloned project no longer contains a validated clip."); }
            setSeconds(clip, validated[i].target.field, validated[i].value);
        }
        app.project.save(); return snapshot();
    }
    function publish(root, command) {
        var response = { protocol_version: PROTOCOL_VERSION, request_id: command.request_id, adapter_id: ADAPTER_ID, source_path: command.source_path, destination_path: command.destination_path, applied_patches: command.patches || [] };
        try { var result = apply(command); response.status = "published"; response.source_fingerprint = command.expected_fingerprint; response.result_fingerprint = result.fingerprint; response.result_snapshot = result; }
        catch (error) { response.status = "rejected"; response.error = String(error); }
        writeJson(new File(root.fsName + "/responses/" + command.request_id + ".json"), response);
    }
    return {
        refresh: function (argument) { try { var config = parse(argument), state = writeState(config); return "Snapshot " + state.fingerprint; } catch (error) { return "Error: " + error; } },
        poll: function (argument) { try { var config = parse(argument), root = requireRoot(config), commands = new Folder(root.fsName + "/commands"), responses = new Folder(root.fsName + "/responses"), files, i, command; writeState(config); if (!config.writable) { return "Read-only snapshot updated."; } if (!commands.exists) { return "No commands."; } if (!responses.exists) { responses.create(); } files = commands.getFiles("*.json"); for (i = 0; i < files.length; i++) { command = readJson(files[i]); if (!new File(responses.fsName + "/" + command.request_id + ".json").exists) { publish(root, command); } } return "Checked " + files.length + " command(s)."; } catch (error) { return "Error: " + error; } }
    };
}());
