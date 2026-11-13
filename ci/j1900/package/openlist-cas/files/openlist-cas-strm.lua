local nixio = require "nixio"
local fs = require "nixio.fs"
local json = require "luci.jsonc"
local util = require "luci.util"

local config_path = "/etc/openlist-cas/strm-generator.json"
local config = json.parse(fs.readfile(config_path) or "")
if not config then
	error("cannot read " .. config_path)
end

local mounts = fs.readfile("/proc/mounts") or ""
if not mounts:find(" /mnt/usb_cicdi ", 1, true) then
	error("CICDI is not mounted; refusing to write STRM files to the root filesystem")
end

local function join_path(left, right)
	if left == "/" then
		return "/" .. right
	end
	return left:gsub("/$", "") .. "/" .. right
end

local function url_encode(value, keep_slash)
	local encoded = {}
	for index = 1, #value do
		local byte = value:byte(index)
		local character = value:sub(index, index)
		local safe = (byte >= 48 and byte <= 57) or (byte >= 65 and byte <= 90) or
			(byte >= 97 and byte <= 122) or character == "-" or character == "." or
			character == "_" or character == "~" or (keep_slash and character == "/")
		encoded[#encoded + 1] = safe and character or string.format("%%%02X", byte)
	end
	return table.concat(encoded)
end

local request_index = 0

local function api(endpoint, payload, authorization)
	request_index = request_index + 1
	local prefix = "/tmp/openlist-strm-" .. tostring(nixio.getpid()) .. "-" .. request_index
	local request_path = prefix .. ".request"
	local response_path = prefix .. ".response"
	fs.writefile(request_path, json.stringify(payload))
	fs.chmod(request_path, "0600")
	local command = "curl --fail --silent --show-error --header 'Content-Type: application/json'"
	if authorization then
		command = command .. " --header " .. util.shellquote("Authorization: " .. authorization)
	end
	command = command .. " --data-binary @" .. util.shellquote(request_path) ..
		" --output " .. util.shellquote(response_path) .. " " ..
		util.shellquote(config.api_base .. endpoint)
	local ok = os.execute(command)
	local body = fs.readfile(response_path) or ""
	fs.unlink(request_path)
	fs.unlink(response_path)
	if ok ~= 0 then
		error("OpenList API request failed: " .. endpoint)
	end
	local response = json.parse(body)
	if not response or response.code ~= 200 then
		error("OpenList API error: " .. tostring(response and response.message or body))
	end
	return response.data
end

local token = api("/api/auth/login", {
	username = config.username,
	password = config.password
}).token

local video_extensions = {
	mp4 = true, mkv = true, avi = true, mov = true, webm = true, flv = true,
	ts = true, m2ts = true, wmv = true, rmvb = true, m4v = true,
	mpg = true, mpeg = true, ["3gp"] = true
}
local created = 0

local function scan(api_path, cloud_path, relative_path)
	local data = api("/api/fs/list", {
		path = api_path,
		password = "",
		page = 1,
		per_page = 0,
		refresh = false
	}, token)
	for _, entry in ipairs(data.content or {}) do
		local child_api = join_path(api_path, entry.name)
		local child_cloud = join_path(cloud_path, entry.name)
		local child_relative = relative_path == "" and entry.name or join_path(relative_path, entry.name)
		if entry.is_dir then
			scan(child_api, child_cloud, child_relative)
		else
			local extension = entry.name:match("%.([^./]+)$")
			if extension and video_extensions[extension:lower()] then
				if not entry.sign or entry.sign == "" then
					error("OpenList did not return a signature for " .. child_cloud)
				end
				local strm_relative = child_relative:gsub("%.[^./]+$", ".strm")
				local destination = join_path(config.destination_root, strm_relative)
				fs.mkdirr(destination:match("^(.*)/[^/]+$") or config.destination_root)
				local url = config.api_base .. "/d" .. url_encode(child_cloud, true) ..
					"?sign=" .. url_encode(entry.sign, false) .. "\n"
				if not fs.writefile(destination, url) then
					error("cannot write " .. destination)
				end
				created = created + 1
			end
		end
	end
end

scan(config.api_path, config.source_root, "")
print(os.date("!%Y-%m-%dT%H:%M:%SZ") .. " generated " .. created .. " STRM file(s)")
