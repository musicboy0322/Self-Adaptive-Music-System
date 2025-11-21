import http from "k6/http";
import { check, sleep } from "k6";

const baseUrl = "http://cartunes-app-acmeair-group6.mycluster-ca-tor-1-835845-04e8c71ff333c8969bc4cbc5a77a70f6-0000.ca-tor.containers.appdomain.cloud"
//const baseUrl = "http://127.0.0.1:8000";

const totalUser = 30;
const createRoomPercentage = 0.1;
const joinRoomPercentage = 0.4;
const addSongPercentage = 0.4;

export const options = {
  scenarios: {
    creators: {
      executor: "constant-vus",
      vus: Math.round(totalUser * createRoomPercentage),
      duration: "20s",
      exec: "createRoom",
    },
    joiners: {
      executor: "constant-vus",
      vus: Math.round(totalUser * joinRoomPercentage),
      duration: "20s",
      exec: "joinRoom",
      startTime: "5s",
    },
    adders: {
      executor: "constant-vus",
      vus: Math.round(totalUser * addSongPercentage),
      duration: "25s",
      exec: "addSong",
      startTime: "10s",
    },
  },
};

export function setup() {
  const rooms = [];
  for (let i = 1; i <= 5; i++) {
    const res = http.post(`${baseUrl}/api/room/create?user_id=creator_${i}&user_name=Creator_${i}`);
    check(res, { "room created": (r) => r.status === 200 });
    rooms.push(res.json("room_id"));
  }

  const joiners = [];
  for (let i = 1; i <= 10; i++) {
    const room = rooms[Math.floor(Math.random() * rooms.length)];
    const userId = `user_${i}`;
    const userName = `Joiner_${i}`;

    const payload = JSON.stringify({ room_id: room, user_id: userId, user_name: userName });
    const res = http.post(`${baseUrl}/api/room/join`, payload, {
      headers: { "Content-Type": "application/json" },
    });

    check(res, { "setup: joined room": (r) => r.status === 200 });
    if (res.status === 200) {
      joiners.push({ user_id: userId, user_name: userName, room_id: room });
    }
  }

  console.log(`✅ Setup done. Rooms: ${JSON.stringify(rooms)}`);
  console.log(`✅ Joined users: ${joiners.length}`);

  return { rooms, joiners };
}

export function createRoom(data) {
  const userId = `creator_${__VU}`;
  const userName = `Creator_${__VU}`;
  const res = http.post(`${baseUrl}/api/room/create?user_id=${userId}&user_name=${userName}`);
  check(res, { "creator: room created": (r) => r.status === 200 });
  sleep(1);
}

export function joinRoom(data) {
  const { rooms } = data;
  const room = rooms[Math.floor(Math.random() * rooms.length)];
  const userId = `user_${__VU}`;
  const userName = `Joiner_${__VU}`;

  const payload = JSON.stringify({ room_id: room, user_id: userId, user_name: userName });
  const res = http.post(`${baseUrl}/api/room/join`, payload, {
    headers: { "Content-Type": "application/json" },
  });

  check(res, { "joined room": (r) => r.status === 200 });
  sleep(1);
}

export function addSong(data) {
  const { joiners } = data;
  const user = joiners[Math.floor(Math.random() * joiners.length)];

  if (!user) {
    console.warn(`[WARN] No valid user found for addSong`);
    return;
  }

  const videoId = `${Math.floor(Math.random() * 100)}_song`;
  const payload = JSON.stringify({
    video_id: videoId,
    title: `Mock Song ${videoId}`,
    channel: "Mock Artist",
    duration: 200,
    thumbnail: "https://picsum.photos/200",
  });

  const res = http.post(
    `${baseUrl}/api/room/${user.room_id}/queue/add?user_id=${user.user_id}&user_name=${user.user_name}`,
    payload,
    { headers: { "Content-Type": "application/json" } }
  );

  check(res, { "song added": (r) => r.status === 200 });
  sleep(1);
}
