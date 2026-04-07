/**
 * Sample TypeScript fixture for testing the JS/TS parser.
 * Mirrors the structure of sample.py.
 */

import { Database } from "./database";
import { EventEmitter } from "events";

export interface User {
    id: number;
    name: string;
    email: string;
    active: boolean;
}

export class UserService {
    private db: Database;

    constructor(db: Database) {
        this.db = db;
    }

    getUser(userId: number): User | null {
        return this.db.findOne("users", { id: userId });
    }

    createUser(name: string, email: string): User {
        return this.db.insert("users", { name, email, active: true });
    }

    static validateEmail(email: string): boolean {
        return email.includes("@") && email.split("@")[1].includes(".");
    }
}

export class AdminService extends UserService {
    deactivateUser(userId: number): boolean {
        return this.db.update("users", { id: userId }, { active: false });
    }
}

export function createApp(config?: Record<string, unknown>): EventEmitter {
    const app = new EventEmitter();
    return app;
}

export function healthCheck(): Record<string, string> {
    return { status: "ok", version: "1.0" };
}
